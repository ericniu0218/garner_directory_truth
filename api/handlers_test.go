package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

func ptr[T any](v T) *T { return &v }

func TestConfidence(t *testing.T) {
	cases := []struct {
		name    string
		risk    *float64
		outcome *string
		want    string
	}{
		{"no score", nil, nil, "unscored"},
		{"low risk", ptr(0.20), nil, "high"},
		{"medium risk boundary", ptr(0.70), nil, "medium"},
		{"high risk boundary", ptr(0.90), nil, "low"},
		{"human check beats a risky score", ptr(0.99), ptr("confirmed"), "verified"},
		{"moved is shown as corrected", ptr(0.10), ptr("moved"), "corrected"},
		{"closed is shown as corrected", nil, ptr("closed"), "corrected"},
		{"unreachable falls back to the score", ptr(0.95), ptr("unreachable"), "low"},
	}
	for _, c := range cases {
		if got := confidence(c.risk, c.outcome); got != c.want {
			t.Errorf("%s: got %q, want %q", c.name, got, c.want)
		}
	}
}

func TestVerificationInputValidate(t *testing.T) {
	ok := verificationInput{Outcome: "confirmed"}
	if err := ok.validate(); err != nil {
		t.Fatalf("confirmed should be valid: %v", err)
	}
	if ok.Source != "manual" {
		t.Errorf("source should default to manual, got %q", ok.Source)
	}
	bad := []verificationInput{
		{Outcome: ""},
		{Outcome: "deleted"},
		{Outcome: "moved"},
		{Outcome: "moved", NewStreet: ptr("  ")},
		{Outcome: "confirmed", Source: "robot"},
	}
	for i, in := range bad {
		if err := in.validate(); err == nil {
			t.Errorf("case %d should be rejected: %+v", i, in)
		}
	}
	moved := verificationInput{Outcome: "moved", NewStreet: ptr("200 5th Ave"), Source: "simulated"}
	if err := moved.validate(); err != nil {
		t.Errorf("moved with a street should be valid: %v", err)
	}
}

func TestLimitParam(t *testing.T) {
	cases := []struct {
		raw  string
		want int
	}{{"", 25}, {"abc", 25}, {"0", 25}, {"-5", 25}, {"10", 10}, {"5000", 100}}
	for _, c := range cases {
		if got := limitParam(c.raw, 25, 100); got != c.want {
			t.Errorf("limitParam(%q) = %d, want %d", c.raw, got, c.want)
		}
	}
}

// Queue and search behavior that lives in SQL. Needs the local database with
// the marts and scores built; skipped otherwise. Every row it writes is tagged
// and removed afterwards.
func TestCheckOutcomesAgainstDatabase(t *testing.T) {
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, env("DATABASE_URL", "postgresql://dt:dt@localhost:5433/directory_truth"))
	if err != nil {
		t.Skip("database not available")
	}
	t.Cleanup(pool.Close) // registered first, so it runs after the row cleanup below

	// The riskiest clinician with no checks on record: first in a risk-ordered queue.
	var npi, lastName, zip string
	err = pool.QueryRow(ctx, `
		select p.npi, p.last_org_name, p.zip5
		from marts.provider_current p join app.scores s using (npi)
		where p.entity_code = 'I'
		  and not exists (select 1 from app.verifications v where v.npi = p.npi)
		order by s.p_stale desc, p.npi limit 1`).Scan(&npi, &lastName, &zip)
	if err != nil {
		t.Skipf("no scored listings available: %v", err)
	}
	clear := func() {
		if _, err := pool.Exec(ctx, `delete from app.verifications where npi = $1 and notes = 'go-test'`, npi); err != nil {
			t.Fatal(err)
		}
	}
	t.Cleanup(clear)

	mux := http.NewServeMux()
	(&Server{db: pool}).Routes(mux)
	call := func(method, path, body string, wantStatus int, out any) {
		t.Helper()
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, httptest.NewRequest(method, path, strings.NewReader(body)))
		if rec.Code != wantStatus {
			t.Fatalf("%s %s: got %d %s", method, path, rec.Code, rec.Body.String())
		}
		if out != nil {
			if err := json.Unmarshal(rec.Body.Bytes(), out); err != nil {
				t.Fatal(err)
			}
		}
	}
	contains := func(path string) bool {
		t.Helper()
		var ps []Provider
		call("GET", path, "", http.StatusOK, &ps)
		for _, p := range ps {
			if p.NPI == npi {
				return true
			}
		}
		return false
	}
	inQueue := func() bool { return contains("/api/queue?sort=risk&limit=5") }
	inSearch := func() bool {
		return contains("/api/providers?limit=100&zip=" + zip + "&q=" + url.QueryEscape(lastName))
	}
	detail := func() Provider {
		t.Helper()
		var out struct {
			Provider Provider `json:"provider"`
		}
		call("GET", "/api/providers/"+npi, "", http.StatusOK, &out)
		return out.Provider
	}
	check := func(body string) {
		t.Helper()
		call("POST", "/api/providers/"+npi+"/verifications", body, http.StatusCreated, nil)
	}

	if !inQueue() || !inSearch() {
		t.Fatal("setup: the listing should start in the queue and in search")
	}

	// Could not reach the office: held back for the retry delay, label unchanged.
	check(`{"outcome":"unreachable","notes":"go-test","source":"simulated"}`)
	if inQueue() {
		t.Error("a listing tried today should wait for the retry delay")
	}
	if got := detail(); got.LastOutcome != nil || got.Confidence != "low" {
		t.Errorf("an unreachable office must not change what members see: %q %v", got.Confidence, got.LastOutcome)
	}
	// Once the retry delay has passed it must come back: nothing was settled.
	if _, err := pool.Exec(ctx, `update app.verifications set created_at = now() - interval '30 days'
		where npi = $1 and notes = 'go-test'`, npi); err != nil {
		t.Fatal(err)
	}
	if !inQueue() {
		t.Error("a listing whose office was unreachable 30 days ago should be back in the queue")
	}
	clear()

	// Moved: leaves the queue, and members get the corrected address.
	check(`{"outcome":"moved","new_street":"1 Test Plaza","new_city":"Testville","new_zip":"10001","notes":"go-test","source":"simulated"}`)
	if got := detail(); got.Confidence != "corrected" || got.CorrectedStreet == nil || *got.CorrectedStreet != "1 Test Plaza" {
		t.Errorf("moved should expose the corrected address: %+v", got)
	}
	if inQueue() {
		t.Error("a corrected listing should leave the queue")
	}
	clear()

	// No longer practicing: leaves the queue and is not offered to members.
	check(`{"outcome":"closed","notes":"go-test","source":"simulated"}`)
	if inQueue() || inSearch() {
		t.Error("a provider found to be no longer practicing should leave the queue and member search")
	}
}
