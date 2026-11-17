package main

import "testing"

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
