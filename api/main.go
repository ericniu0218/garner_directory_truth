// Directory Truth API: serves provider search, the verification queue, and
// records verification outcomes. Reads dbt marts and the scores table.
package main

import (
	"context"
	_ "embed"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed schema.sql
var schemaSQL string

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, env("DATABASE_URL", "postgresql://dt:dt@localhost:5433/directory_truth"))
	if err != nil {
		log.Fatalf("connect: %v", err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, schemaSQL); err != nil {
		log.Fatalf("apply schema: %v", err)
	}

	srv := &Server{db: pool, parser: NewNoteParser()}
	mux := http.NewServeMux()
	srv.Routes(mux)
	if dir := os.Getenv("STATIC_DIR"); dir != "" {
		mux.Handle("/", http.FileServer(http.Dir(dir)))
	}

	addr := ":" + env("PORT", "8080")
	httpSrv := &http.Server{
		Addr:              addr,
		Handler:           logRequests(mux),
		ReadHeaderTimeout: 10 * time.Second,
	}
	log.Printf("listening on %s", addr)
	log.Fatal(httpSrv.ListenAndServe())
}

func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		log.Printf("%s %s %s", r.Method, r.URL.Path, time.Since(start).Round(time.Millisecond))
	})
}
