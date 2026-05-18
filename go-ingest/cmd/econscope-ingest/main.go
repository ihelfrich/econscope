// econscope-ingest — concurrent data ingest engine for ECONSCOPE.
//
// Pulls from multiple APIs in parallel with per-source rate limiting,
// writes Parquet files to the staging directory. The Python layer
// loads staging Parquet into the DuckDB warehouse.
//
// Usage:
//
//	econscope-ingest pull treasury debt_to_penny --start 2024-01-01
//	econscope-ingest pull-all --start 2024-01-01
//	econscope-ingest sources
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ihelfrich/econscope/go-ingest/internal/adapter"
	"github.com/ihelfrich/econscope/go-ingest/internal/ratelimit"
	"github.com/ihelfrich/econscope/go-ingest/internal/staging"
	"golang.org/x/sync/errgroup"

	// Register adapters — each adapter's init() calls adapter.Register()
	_ "github.com/ihelfrich/econscope/go-ingest/internal/adapter"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(1)
	}

	// Default staging dir: ../data/staging relative to binary, or ./data/staging
	defaultStaging := filepath.Join(".", "data", "staging")
	if dir, err := findProjectRoot(); err == nil {
		defaultStaging = filepath.Join(dir, "data", "staging")
	}

	switch os.Args[1] {
	case "sources":
		cmdSources()
	case "pull":
		cmdPull(os.Args[2:], defaultStaging)
	case "pull-all":
		cmdPullAll(os.Args[2:], defaultStaging)
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", os.Args[1])
		usage()
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "Usage:")
	fmt.Fprintln(os.Stderr, "  econscope-ingest sources")
	fmt.Fprintln(os.Stderr, "  econscope-ingest pull <source> <series_id> [--start DATE] [--end DATE]")
	fmt.Fprintln(os.Stderr, "  econscope-ingest pull-all [--start DATE] [--end DATE]")
}

func cmdSources() {
	fmt.Printf("%-12s %s\n", "SOURCE", "RATE (req/s)")
	fmt.Println(strings.Repeat("-", 30))
	for id, a := range adapter.Registry {
		fmt.Printf("%-12s %.1f\n", id, a.RateLimit())
	}
}

func cmdPull(args []string, stagingDir string) {
	fs := flag.NewFlagSet("pull", flag.ExitOnError)
	start := fs.String("start", "", "Start date (YYYY-MM-DD)")
	end := fs.String("end", "", "End date (YYYY-MM-DD)")
	fs.Parse(args)

	if fs.NArg() < 2 {
		fmt.Fprintln(os.Stderr, "pull requires <source> <series_id>")
		os.Exit(1)
	}

	source := fs.Arg(0)
	seriesID := fs.Arg(1)

	a, ok := adapter.Registry[source]
	if !ok {
		fmt.Fprintf(os.Stderr, "unknown source: %s\n", source)
		os.Exit(1)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	req := adapter.PullRequest{
		Source:   source,
		SeriesID: seriesID,
		Start:    *start,
		End:      *end,
	}

	t0 := time.Now()
	result := a.Pull(ctx, req)
	elapsed := time.Since(t0)

	if result.Error != nil {
		fmt.Fprintf(os.Stderr, "ERROR: %v\n", result.Error)
		os.Exit(1)
	}

	writer := staging.NewWriter(stagingDir)
	path, err := writer.Write(result)
	if err != nil {
		fmt.Fprintf(os.Stderr, "staging write error: %v\n", err)
		os.Exit(1)
	}

	fmt.Fprintf(os.Stderr, "Pulled %d observations for %s:%s in %s\n",
		len(result.Observations), source, seriesID, elapsed.Round(time.Millisecond))
	fmt.Fprintf(os.Stderr, "Staged: %s\n", path)
}

func cmdPullAll(args []string, stagingDir string) {
	fs := flag.NewFlagSet("pull-all", flag.ExitOnError)
	start := fs.String("start", "", "Start date (YYYY-MM-DD)")
	end := fs.String("end", "", "End date (YYYY-MM-DD)")
	fs.Parse(args)

	pool := ratelimit.NewPool()
	for id, a := range adapter.Registry {
		pool.Set(id, a.RateLimit())
	}

	writer := staging.NewWriter(stagingDir)

	// Pull from all sources concurrently
	g, ctx := errgroup.WithContext(context.Background())
	g.SetLimit(len(adapter.Registry)) // one goroutine per source

	t0 := time.Now()
	totalObs := 0
	totalFiles := 0

	for id, a := range adapter.Registry {
		id, a := id, a // capture loop vars
		g.Go(func() error {
			if err := pool.Wait(ctx, id); err != nil {
				return err
			}

			// For now, each adapter has a default series list
			// This will be driven by a manifest file later
			req := adapter.PullRequest{
				Source:   id,
				SeriesID: getDefaultSeries(id),
				Start:    *start,
				End:      *end,
			}

			result := a.Pull(ctx, req)
			if result.Error != nil {
				fmt.Fprintf(os.Stderr, "  %s: ERROR: %v\n", id, result.Error)
				return nil // don't stop other pulls
			}

			path, err := writer.Write(result)
			if err != nil {
				fmt.Fprintf(os.Stderr, "  %s: staging error: %v\n", id, err)
				return nil
			}

			fmt.Fprintf(os.Stderr, "  %s: %d obs → %s\n", id, len(result.Observations), filepath.Base(path))
			totalObs += len(result.Observations)
			totalFiles++
			return nil
		})
	}

	if err := g.Wait(); err != nil {
		fmt.Fprintf(os.Stderr, "pull-all error: %v\n", err)
		os.Exit(1)
	}

	fmt.Fprintf(os.Stderr, "\nDone: %d files, %d total observations in %s\n",
		totalFiles, totalObs, time.Since(t0).Round(time.Millisecond))
}

func getDefaultSeries(source string) string {
	defaults := map[string]string{
		"treasury": "debt_to_penny",
	}
	if s, ok := defaults[source]; ok {
		return s
	}
	return ""
}

func findProjectRoot() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "pyproject.toml")); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("project root not found")
		}
		dir = parent
	}
}
