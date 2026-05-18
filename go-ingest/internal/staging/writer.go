// Package staging writes PullResults to Parquet files in the staging directory.
//
// Layout: staging/{source}/{series_id}_{timestamp}.parquet
// The Python loader reads staging/**/*.parquet into DuckDB.
package staging

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ihelfrich/econscope/go-ingest/internal/adapter"
	"github.com/parquet-go/parquet-go"
)

// Writer manages the staging directory and writes Parquet files.
type Writer struct {
	BaseDir string
}

// NewWriter creates a staging writer.
func NewWriter(baseDir string) *Writer {
	return &Writer{BaseDir: baseDir}
}

// Write persists a PullResult as a Parquet file. Returns the file path written.
func (w *Writer) Write(result adapter.PullResult) (string, error) {
	if len(result.Observations) == 0 {
		return "", fmt.Errorf("no observations to write for %s:%s", result.Source, result.SeriesID)
	}

	// Create source directory
	dir := filepath.Join(w.BaseDir, result.Source)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("mkdir %s: %w", dir, err)
	}

	// Sanitize series ID for filename
	safe := strings.ReplaceAll(result.SeriesID, "/", "_")
	safe = strings.ReplaceAll(safe, ":", "_")
	safe = strings.ReplaceAll(safe, " ", "_")
	ts := time.Now().UTC().Format("20060102T150405")
	filename := fmt.Sprintf("%s_%s.parquet", safe, ts)
	path := filepath.Join(dir, filename)

	f, err := os.Create(path)
	if err != nil {
		return "", fmt.Errorf("create %s: %w", path, err)
	}
	defer f.Close()

	pw := parquet.NewGenericWriter[adapter.Observation](f)

	if _, err := pw.Write(result.Observations); err != nil {
		return "", fmt.Errorf("write parquet rows: %w", err)
	}

	if err := pw.Close(); err != nil {
		return "", fmt.Errorf("close parquet writer: %w", err)
	}

	return path, nil
}
