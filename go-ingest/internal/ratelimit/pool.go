// Package ratelimit provides per-source rate limiters for the ingest engine.
package ratelimit

import (
	"context"
	"sync"

	"golang.org/x/time/rate"
)

// Pool manages per-source rate limiters.
type Pool struct {
	mu       sync.RWMutex
	limiters map[string]*rate.Limiter
}

// NewPool creates a rate limiter pool.
func NewPool() *Pool {
	return &Pool{
		limiters: make(map[string]*rate.Limiter),
	}
}

// Set configures the rate limit for a source (requests per second).
func (p *Pool) Set(source string, rps float64) {
	p.mu.Lock()
	defer p.mu.Unlock()
	// Allow burst of up to 3 requests
	burst := int(rps)
	if burst < 1 {
		burst = 1
	}
	if burst > 5 {
		burst = 5
	}
	p.limiters[source] = rate.NewLimiter(rate.Limit(rps), burst)
}

// Wait blocks until the rate limiter for the given source allows a request.
func (p *Pool) Wait(ctx context.Context, source string) error {
	p.mu.RLock()
	lim, ok := p.limiters[source]
	p.mu.RUnlock()

	if !ok {
		// No limiter configured — allow immediately
		return nil
	}
	return lim.Wait(ctx)
}
