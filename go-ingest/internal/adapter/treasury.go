// Treasury FiscalData adapter — the first Go adapter.
// No API key needed. Demonstrates the pattern for all others.
package adapter

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const treasuryBase = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

type treasuryEndpoint struct {
	Path       string
	Title      string
	ValueField string
}

var treasuryEndpoints = map[string]treasuryEndpoint{
	"debt_to_penny":     {"v2/accounting/od/debt_to_penny", "Federal Debt to the Penny", "tot_pub_debt_out_amt"},
	"avg_interest_rates": {"v2/accounting/od/avg_interest_rates", "Average Interest Rates on Treasury Securities", "avg_interest_rate_amt"},
	"daily_treasury":     {"v1/accounting/dts/dts_table_1", "Daily Treasury Statement", "close_today_bal"},
	"savings_bonds":      {"v2/accounting/od/savings_bonds_report", "Savings Bonds Report", "securities_outstanding_amt"},
}

type Treasury struct{}

func init() {
	Register(&Treasury{})
}

func (t *Treasury) SourceID() string    { return "treasury" }
func (t *Treasury) RateLimit() float64  { return 2.0 } // conservative

func (t *Treasury) Pull(ctx context.Context, req PullRequest) PullResult {
	ep, ok := treasuryEndpoints[req.SeriesID]
	if !ok {
		// Treat series_id as raw endpoint path
		ep = treasuryEndpoint{Path: req.SeriesID, Title: req.SeriesID, ValueField: ""}
	}

	params := url.Values{}
	params.Set("page[size]", "10000")
	params.Set("sort", "-record_date")

	var filters []string
	if req.Start != "" {
		filters = append(filters, "record_date:gte:"+req.Start)
	}
	if req.End != "" {
		filters = append(filters, "record_date:lte:"+req.End)
	}
	if len(filters) > 0 {
		params.Set("filter", strings.Join(filters, ","))
	}

	apiURL := fmt.Sprintf("%s/%s?%s", treasuryBase, ep.Path, params.Encode())

	httpReq, err := http.NewRequestWithContext(ctx, "GET", apiURL, nil)
	if err != nil {
		return PullResult{Source: "treasury", SeriesID: req.SeriesID, Error: err}
	}

	resp, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		return PullResult{Source: "treasury", SeriesID: req.SeriesID, Error: err}
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return PullResult{Source: "treasury", SeriesID: req.SeriesID, Error: err}
	}

	var body struct {
		Data []map[string]interface{} `json:"data"`
	}
	if err := json.Unmarshal(raw, &body); err != nil {
		return PullResult{Source: "treasury", SeriesID: req.SeriesID, Error: err, RawBytes: raw}
	}

	valueField := ep.ValueField
	// Auto-detect value field if not set
	if valueField == "" && len(body.Data) > 0 {
		for k, v := range body.Data[0] {
			if k == "record_date" {
				continue
			}
			if s, ok := v.(string); ok {
				if _, err := strconv.ParseFloat(strings.ReplaceAll(s, ",", ""), 64); err == nil {
					valueField = k
					break
				}
			}
		}
	}

	var obs []Observation
	for _, row := range body.Data {
		dateStr, _ := row["record_date"].(string)
		if dateStr == "" {
			continue
		}
		dt, err := time.Parse("2006-01-02", dateStr)
		if err != nil {
			continue
		}
		dt = dt.UTC() // normalize to UTC

		valStr, _ := row[valueField].(string)
		val, err := strconv.ParseFloat(strings.ReplaceAll(valStr, ",", ""), 64)
		if err != nil {
			continue
		}

		obs = append(obs, Observation{
			Source:   "treasury",
			SeriesID: req.SeriesID,
			Date:     dt,
			Value:    val,
		})
	}

	return PullResult{
		Source:       "treasury",
		SeriesID:     req.SeriesID,
		Observations: obs,
		Title:        ep.Title,
		Units:        "USD",
		RawBytes:     raw,
	}
}
