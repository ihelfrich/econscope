// Package adapter defines the interface every data source must implement.
//
// Each adapter pulls data from a single API and returns typed rows ready
// for Parquet serialization. The Go ingest layer handles concurrency,
// rate-limiting, retries, and staging — adapters just do HTTP + parse.
package adapter

import (
	"context"
	"time"
)

// Observation is a single data point from any source.
type Observation struct {
	Source   string    `parquet:"source"`
	SeriesID string   `parquet:"series_id"`
	Date     time.Time `parquet:"date,timestamp(millisecond)"`
	Value    float64   `parquet:"value"`
	Unit     string    `parquet:"unit,optional"`
	GeoName  string    `parquet:"geo_name,optional"`
	GeoCode  string    `parquet:"geo_code,optional"`
	Extra    string    `parquet:"extra,optional"` // JSON blob for adapter-specific fields
}

// PullRequest describes what to pull.
type PullRequest struct {
	Source   string
	SeriesID string
	Start    string // YYYY-MM-DD or empty
	End      string // YYYY-MM-DD or empty
}

// PullResult is what an adapter returns.
type PullResult struct {
	Source       string
	SeriesID     string
	Observations []Observation
	Title        string
	Frequency    string
	Units        string
	RawBytes     []byte
	Error        error
}

// Adapter is the interface every data source must implement.
type Adapter interface {
	// SourceID returns the unique source identifier (e.g., "fred", "treasury").
	SourceID() string

	// Pull fetches observations for a single series.
	Pull(ctx context.Context, req PullRequest) PullResult

	// RateLimit returns the maximum requests per second for this source.
	RateLimit() float64
}

// Registry holds all known adapters keyed by source ID.
var Registry = map[string]Adapter{}

// Register adds an adapter to the global registry. Called from init() in
// each adapter package.
func Register(a Adapter) {
	Registry[a.SourceID()] = a
}
