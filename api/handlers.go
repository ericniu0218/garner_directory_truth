package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// A check that reached the office (confirmed, moved, closed) counts as current
// for this long: the listing leaves the queue and the member view shows the
// checked result instead of the model score.
const verificationFreshDays = 180

// "Could not reach the office" settles nothing, so the listing stays in the
// queue. It is only held back this long so the same office is not called twice
// in a row.
const unreachableRetryDays = 7

type Server struct {
	db     *pgxpool.Pool
	parser *NoteParser
}

func (s *Server) Routes(mux *http.ServeMux) {
	mux.HandleFunc("GET /healthz", s.health)
	mux.HandleFunc("GET /api/specialties", s.specialties)
	mux.HandleFunc("GET /api/providers", s.searchProviders)
	mux.HandleFunc("GET /api/providers/{npi}", s.providerDetail)
	mux.HandleFunc("POST /api/providers/{npi}/verifications", s.createVerification)
	mux.HandleFunc("GET /api/queue", s.queue)
	mux.HandleFunc("GET /api/metrics", s.metrics)
	mux.HandleFunc("POST /api/parse-note", s.parseNote)
}

type Reason struct {
	Code string `json:"code"`
	Text string `json:"text"`
}

type Provider struct {
	NPI                      string     `json:"npi"`
	Name                     string     `json:"name"`
	Credentials              *string    `json:"credentials"`
	EntityCode               string     `json:"entity_code"`
	Specialty                string     `json:"specialty"`
	Street1                  *string    `json:"street1"`
	Street2                  *string    `json:"street2"`
	City                     *string    `json:"city"`
	State                    *string    `json:"state"`
	Zip5                     *string    `json:"zip5"`
	DataYear                 int        `json:"data_year"`
	MedicarePatients         *int64     `json:"medicare_patients"`
	TenureYears              int        `json:"tenure_years"`
	PStale                   *float64   `json:"p_stale"`
	PMove                    *float64   `json:"p_move"`
	RiskPct                  *float64   `json:"risk_pct"`
	ExpectedPatientsAffected *float64   `json:"expected_patients_affected"`
	Reasons                  []Reason   `json:"reasons"`
	Confidence               string     `json:"confidence"` // verified | corrected | high | medium | low | unscored
	LastVerifiedAt           *time.Time `json:"last_verified_at"`
	LastOutcome              *string    `json:"last_outcome"`
	// Set when the last check found a new address. The member view shows this
	// instead of the address on file.
	CorrectedStreet *string `json:"corrected_street"`
	CorrectedCity   *string `json:"corrected_city"`
	CorrectedZip    *string `json:"corrected_zip"`
}

// providerSelect returns one row per current listing joined to its score and
// its most recent fresh verification.
const providerSelect = `
select
    p.npi,
    trim(concat_ws(' ', p.first_name, p.last_org_name)) as name,
    p.credentials, p.entity_code, p.provider_type,
    p.street1, p.street2, p.city, p.state, p.zip5,
    p.data_year, p.tot_benes, p.tenure_years,
    s.p_stale, s.p_move, s.risk_pct, s.expected_patients_affected,
    coalesce(s.reasons, '[]'::jsonb) as reasons,
    v.created_at as last_verified_at, v.outcome as last_outcome,
    v.new_street, v.new_city, v.new_zip
from marts.provider_current p
left join app.scores s on s.npi = p.npi
left join lateral (
    select created_at, outcome, new_street, new_city, new_zip
    from app.verifications
    where npi = p.npi and outcome <> 'unreachable' and created_at > now() - make_interval(days => ` + "$1" + `)
    order by created_at desc
    limit 1
) v on true
`

func scanProviders(rows pgx.Rows) ([]Provider, error) {
	defer rows.Close()
	out := []Provider{}
	for rows.Next() {
		var p Provider
		var reasons []byte
		if err := rows.Scan(
			&p.NPI, &p.Name, &p.Credentials, &p.EntityCode, &p.Specialty,
			&p.Street1, &p.Street2, &p.City, &p.State, &p.Zip5,
			&p.DataYear, &p.MedicarePatients, &p.TenureYears,
			&p.PStale, &p.PMove, &p.RiskPct, &p.ExpectedPatientsAffected,
			&reasons, &p.LastVerifiedAt, &p.LastOutcome,
			&p.CorrectedStreet, &p.CorrectedCity, &p.CorrectedZip,
		); err != nil {
			return nil, err
		}
		if err := json.Unmarshal(reasons, &p.Reasons); err != nil {
			return nil, err
		}
		p.Confidence = confidence(p.RiskPct, p.LastOutcome)
		out = append(out, p)
	}
	return out, rows.Err()
}

// confidence turns a score and verification state into the label a member sees.
// A fresh human check always outranks the model.
func confidence(riskPct *float64, lastOutcome *string) string {
	if lastOutcome != nil {
		switch *lastOutcome {
		case "confirmed":
			return "verified"
		case "moved", "closed":
			return "corrected"
		}
	}
	switch {
	case riskPct == nil:
		return "unscored"
	case *riskPct >= 0.90:
		return "low"
	case *riskPct >= 0.70:
		return "medium"
	default:
		return "high"
	}
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	if err := s.db.Ping(r.Context()); err != nil {
		writeError(w, http.StatusServiceUnavailable, "database unavailable")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) specialties(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(r.Context(), `
		select provider_type, count(*) from marts.provider_current
		where provider_type is not null group by 1 order by 2 desc`)
	if err != nil {
		serverError(w, err)
		return
	}
	defer rows.Close()
	type item struct {
		Specialty string `json:"specialty"`
		Count     int    `json:"count"`
	}
	out := []item{}
	for rows.Next() {
		var it item
		if err := rows.Scan(&it.Specialty, &it.Count); err != nil {
			serverError(w, err)
			return
		}
		out = append(out, it)
	}
	writeJSON(w, http.StatusOK, out)
}

// searchProviders is the member view: find providers by zip and specialty.
// Verified and high-confidence listings are shown first.
func (s *Server) searchProviders(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	args := []any{verificationFreshDays}
	// A provider a reviewer found to be no longer practicing is not offered to members.
	where := []string{"v.outcome is distinct from 'closed'"}
	if zip := strings.TrimSpace(q.Get("zip")); zip != "" {
		args = append(args, zip+"%")
		where = append(where, "p.zip5 like $"+strconv.Itoa(len(args)))
	}
	if sp := q.Get("specialty"); sp != "" {
		args = append(args, sp)
		where = append(where, "p.provider_type = $"+strconv.Itoa(len(args)))
	}
	if name := strings.TrimSpace(q.Get("q")); name != "" {
		args = append(args, "%"+name+"%")
		where = append(where, "concat_ws(' ', p.first_name, p.last_org_name) ilike $"+strconv.Itoa(len(args)))
	}
	args = append(args, limitParam(q.Get("limit"), 25, 100))
	sql := providerSelect + " where " + strings.Join(where, " and ") + `
		order by (v.outcome = 'confirmed') desc nulls last, s.risk_pct asc nulls last, p.tot_benes desc nulls last
		limit $` + strconv.Itoa(len(args))
	rows, err := s.db.Query(r.Context(), sql, args...)
	if err != nil {
		serverError(w, err)
		return
	}
	providers, err := scanProviders(rows)
	if err != nil {
		serverError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, providers)
}

// queue is the reviewer view: doubtful listings ranked by expected patients
// affected (chance the listing is stale x patients who rely on it). Listings
// with a fresh check that reached the office are left out; an unreachable
// office comes back after a short retry delay.
func (s *Server) queue(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	args := []any{verificationFreshDays}
	where := []string{
		"s.npi is not null",
		"v.created_at is null",
		`not exists (select 1 from app.verifications u where u.npi = p.npi and u.outcome = 'unreachable'
			and u.created_at > now() - make_interval(days => ` + strconv.Itoa(unreachableRetryDays) + `))`,
	}
	if sp := q.Get("specialty"); sp != "" {
		args = append(args, sp)
		where = append(where, "p.provider_type = $"+strconv.Itoa(len(args)))
	}
	// A member directory lists clinicians, so labs and other organizations
	// are left out unless asked for.
	if q.Get("entity") != "all" {
		where = append(where, "p.entity_code = 'I'")
	}
	// Policy: only queue listings the model doubts (default: riskiest 30%),
	// then order those by how many patients rely on them.
	minRisk := 0.70
	if v, err := strconv.ParseFloat(q.Get("min_risk"), 64); err == nil && v >= 0 && v <= 1 {
		minRisk = v
	}
	args = append(args, minRisk)
	where = append(where, "s.risk_pct >= $"+strconv.Itoa(len(args)))
	order := "s.expected_patients_affected desc"
	if q.Get("sort") == "risk" {
		order = "s.p_stale desc"
	}
	args = append(args, limitParam(q.Get("limit"), 50, 200))
	sql := providerSelect + " where " + strings.Join(where, " and ") +
		" order by " + order + ", p.npi limit $" + strconv.Itoa(len(args))
	rows, err := s.db.Query(r.Context(), sql, args...)
	if err != nil {
		serverError(w, err)
		return
	}
	providers, err := scanProviders(rows)
	if err != nil {
		serverError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, providers)
}

type HistoryRow struct {
	DataYear         int     `json:"data_year"`
	Street1          *string `json:"street1"`
	City             *string `json:"city"`
	Zip5             *string `json:"zip5"`
	MedicarePatients *int64  `json:"medicare_patients"`
	MovedNextYear    *bool   `json:"moved_next_year"`
}

type Verification struct {
	ID                   int64     `json:"id"`
	Outcome              string    `json:"outcome"`
	NewStreet            *string   `json:"new_street"`
	NewCity              *string   `json:"new_city"`
	NewZip               *string   `json:"new_zip"`
	NewPhone             *string   `json:"new_phone"`
	AcceptingNewPatients *bool     `json:"accepting_new_patients"`
	Notes                *string   `json:"notes"`
	Source               string    `json:"source"`
	CreatedAt            time.Time `json:"created_at"`
}

func (s *Server) providerDetail(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	npi := r.PathValue("npi")
	rows, err := s.db.Query(ctx, providerSelect+" where p.npi = $2", verificationFreshDays, npi)
	if err != nil {
		serverError(w, err)
		return
	}
	providers, err := scanProviders(rows)
	if err != nil {
		serverError(w, err)
		return
	}
	if len(providers) == 0 {
		writeError(w, http.StatusNotFound, "provider not found")
		return
	}

	history, err := s.history(ctx, npi)
	if err != nil {
		serverError(w, err)
		return
	}
	verifications, err := s.verifications(ctx, npi)
	if err != nil {
		serverError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"provider":      providers[0],
		"history":       history,
		"verifications": verifications,
	})
}

func (s *Server) history(ctx context.Context, npi string) ([]HistoryRow, error) {
	rows, err := s.db.Query(ctx, `
		select data_year, street1, city, zip5, tot_benes, moved_next_year
		from marts.provider_features where npi = $1 order by data_year`, npi)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []HistoryRow{}
	for rows.Next() {
		var h HistoryRow
		if err := rows.Scan(&h.DataYear, &h.Street1, &h.City, &h.Zip5, &h.MedicarePatients, &h.MovedNextYear); err != nil {
			return nil, err
		}
		out = append(out, h)
	}
	return out, rows.Err()
}

func (s *Server) verifications(ctx context.Context, npi string) ([]Verification, error) {
	rows, err := s.db.Query(ctx, `
		select id, outcome, new_street, new_city, new_zip, new_phone,
		       accepting_new_patients, notes, source, created_at
		from app.verifications where npi = $1 order by created_at desc`, npi)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Verification{}
	for rows.Next() {
		var v Verification
		if err := rows.Scan(&v.ID, &v.Outcome, &v.NewStreet, &v.NewCity, &v.NewZip, &v.NewPhone,
			&v.AcceptingNewPatients, &v.Notes, &v.Source, &v.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

type verificationInput struct {
	Outcome              string  `json:"outcome"`
	NewStreet            *string `json:"new_street"`
	NewCity              *string `json:"new_city"`
	NewZip               *string `json:"new_zip"`
	NewPhone             *string `json:"new_phone"`
	AcceptingNewPatients *bool   `json:"accepting_new_patients"`
	Notes                *string `json:"notes"`
	Source               string  `json:"source"`
}

var validOutcomes = map[string]bool{"confirmed": true, "moved": true, "closed": true, "unreachable": true}

func (in *verificationInput) validate() error {
	if !validOutcomes[in.Outcome] {
		return errors.New("outcome must be one of confirmed, moved, closed, unreachable")
	}
	if in.Outcome == "moved" && (in.NewStreet == nil || strings.TrimSpace(*in.NewStreet) == "") {
		return errors.New("new_street is required when outcome is moved")
	}
	if in.Source == "" {
		in.Source = "manual"
	}
	if in.Source != "manual" && in.Source != "simulated" {
		return errors.New("source must be manual or simulated")
	}
	return nil
}

func (s *Server) createVerification(w http.ResponseWriter, r *http.Request) {
	npi := r.PathValue("npi")
	var in verificationInput
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&in); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if err := in.validate(); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	var exists bool
	if err := s.db.QueryRow(r.Context(),
		`select exists (select 1 from marts.provider_current where npi = $1)`, npi).Scan(&exists); err != nil {
		serverError(w, err)
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "provider not found")
		return
	}
	var v Verification
	err := s.db.QueryRow(r.Context(), `
		insert into app.verifications
		    (npi, outcome, new_street, new_city, new_zip, new_phone, accepting_new_patients, notes, source)
		values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		returning id, outcome, new_street, new_city, new_zip, new_phone,
		          accepting_new_patients, notes, source, created_at`,
		npi, in.Outcome, in.NewStreet, in.NewCity, in.NewZip, in.NewPhone,
		in.AcceptingNewPatients, in.Notes, in.Source,
	).Scan(&v.ID, &v.Outcome, &v.NewStreet, &v.NewCity, &v.NewZip, &v.NewPhone,
		&v.AcceptingNewPatients, &v.Notes, &v.Source, &v.CreatedAt)
	if err != nil {
		serverError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, v)
}

func (s *Server) metrics(w http.ResponseWriter, r *http.Request) {
	var version string
	var createdAt time.Time
	var metrics json.RawMessage
	err := s.db.QueryRow(r.Context(), `
		select model_version, created_at, metrics from app.model_runs
		order by created_at desc limit 1`).Scan(&version, &createdAt, &metrics)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "no model run recorded yet")
		return
	}
	if err != nil {
		serverError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"model_version": version, "created_at": createdAt, "metrics": metrics,
	})
}

func (s *Server) parseNote(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Note string `json:"note"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&in); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if strings.TrimSpace(in.Note) == "" {
		writeError(w, http.StatusBadRequest, "note is required")
		return
	}
	parsed, err := s.parser.Parse(r.Context(), in.Note)
	if errors.Is(err, ErrParserNotConfigured) {
		writeError(w, http.StatusServiceUnavailable, "note parser is not configured: set ANTHROPIC_API_KEY")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadGateway, "note parser failed: "+err.Error())
		return
	}
	writeJSON(w, http.StatusOK, parsed)
}

func limitParam(raw string, fallback, max int) int {
	n, err := strconv.Atoi(raw)
	if err != nil || n < 1 {
		return fallback
	}
	if n > max {
		return max
	}
	return n
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func serverError(w http.ResponseWriter, err error) {
	// Log the detail, return a generic message.
	log.Printf("error: %v", err)
	writeError(w, http.StatusInternalServerError, "internal error")
}
