package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"

	"github.com/anthropics/anthropic-sdk-go/v2"
)

// NoteParser turns a reviewer's free-text call note into structured fields.
// It only proposes values: the reviewer confirms them in the UI before anything
// is saved, because a wrong phone number or address would mislead a member.
type NoteParser struct {
	client  *anthropic.Client
	model   string
	enabled bool
}

var ErrParserNotConfigured = errors.New("note parser not configured")

// ParsedNote mirrors the tool schema below. Fields the note does not state are null.
type ParsedNote struct {
	Outcome              string  `json:"outcome"`
	NewStreet            *string `json:"new_street"`
	NewCity              *string `json:"new_city"`
	NewZip               *string `json:"new_zip"`
	NewPhone             *string `json:"new_phone"`
	AcceptingNewPatients *bool   `json:"accepting_new_patients"`
	Confidence           string  `json:"confidence"`
	Evidence             string  `json:"evidence"`
	// Model is set by the server (not by Claude) so results can be traced to
	// the model that produced them.
	Model string `json:"model"`
}

const parserSystemPrompt = `You help a healthcare directory team record the result of a phone call to a doctor's office.

A reviewer called the office to check whether a provider's directory listing is still correct, then typed a short free-text note. Read the note and record the outcome by calling the record_call_outcome tool exactly once.

How to choose the outcome:
- confirmed: the office said the provider still practices at the listed address, with no change to the suite or floor.
- moved: the provider now practices at a different address. This includes a different suite or floor in the same building, because patients use the suite to find the office. Fill in whatever parts of the new address or phone the note gives; for a suite change, record only the part the note states.
- A move that has not happened yet (for example "moving next month") is still confirmed, because the listed address is correct today.
- closed: the provider retired, died, left medicine, or the practice shut down, with no new location.
- unreachable: nobody gave an answer (no pickup, voicemail, disconnected number, or the person did not know).

The values you record are shown to the reviewer for confirmation and may then appear in a directory that patients rely on, so accuracy matters more than completeness. Record only what the note states. If the note does not mention a field, set it to null rather than inferring it. Copy addresses and phone numbers as written; do not correct or complete them. Set accepting_new_patients only when the note says so explicitly.

Set confidence to "low" when the note is ambiguous, contradicts itself, or reports second-hand information; otherwise "high". In evidence, quote the few words of the note that support the outcome.`

func NewNoteParser() *NoteParser {
	p := &NoteParser{model: env("NOTE_PARSER_MODEL", "claude-opus-5-5")}
	if os.Getenv("ANTHROPIC_API_KEY") == "" && os.Getenv("ANTHROPIC_AUTH_TOKEN") == "" {
		return p
	}
	client := anthropic.NewClient()
	p.client = &client
	p.enabled = true
	return p
}

func nullable(t string) map[string]any {
	return map[string]any{"type": []string{t, "null"}}
}

func (p *NoteParser) Parse(ctx context.Context, note string) (*ParsedNote, error) {
	if !p.enabled {
		return nil, ErrParserNotConfigured
	}
	tool := anthropic.ToolParam{
		Name:        "record_call_outcome",
		Description: anthropic.String("Record the structured result of a directory verification call."),
		Strict:      anthropic.Bool(true),
		InputSchema: anthropic.ToolInputSchemaParam{
			Properties: map[string]any{
				"outcome": map[string]any{
					"type": "string",
					"enum": []string{"confirmed", "moved", "closed", "unreachable"},
				},
				"new_street":             nullable("string"),
				"new_city":               nullable("string"),
				"new_zip":                nullable("string"),
				"new_phone":              nullable("string"),
				"accepting_new_patients": nullable("boolean"),
				"confidence":             map[string]any{"type": "string", "enum": []string{"high", "low"}},
				"evidence":               map[string]any{"type": "string"},
			},
			Required: []string{
				"outcome", "new_street", "new_city", "new_zip", "new_phone",
				"accepting_new_patients", "confidence", "evidence",
			},
			ExtraFields: map[string]any{"additionalProperties": false},
		},
	}
	resp, err := p.client.Messages.New(ctx, anthropic.MessageNewParams{
		Model:     anthropic.Model(p.model),
		MaxTokens: 2000,
		System:    []anthropic.TextBlockParam{{Text: parserSystemPrompt}},
		Tools:     []anthropic.ToolUnionParam{{OfTool: &tool}},
		Messages: []anthropic.MessageParam{
			anthropic.NewUserMessage(anthropic.NewTextBlock("Call note:\n" + note)),
		},
	})
	if err != nil {
		return nil, err
	}
	if resp.StopReason == anthropic.StopReasonRefusal {
		return nil, errors.New("model declined the request")
	}
	for _, block := range resp.Content {
		if use, ok := block.AsAny().(anthropic.ToolUseBlock); ok && use.Name == tool.Name {
			var parsed ParsedNote
			if err := json.Unmarshal(use.Input, &parsed); err != nil {
				return nil, fmt.Errorf("decode tool input: %w", err)
			}
			parsed.Model = p.model
			return &parsed, nil
		}
	}
	return nil, errors.New("model did not record an outcome")
}
