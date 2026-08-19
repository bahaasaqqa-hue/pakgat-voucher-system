# Pakgat AI Company — Master Checklist

Source of truth: `Pakgat_AI_Company_Blueprint_V1` (17 Aug 2026).
Production rule: all runtime, Data Hub, Dashboard and monitoring are on Google Compute Engine. GitHub is source control only. Render is retired from the target architecture.

## Completion rule
A Blueprint item is not marked complete merely because a screen, table or placeholder exists. It is complete only when the data source is connected, the workflow is running, the result is visible in the Control Center, and a real production-safe check has passed.

## 1. Executive / CEO & AI Command Center
- [x] Protected Control Center on Google
- [x] Company Health
- [x] Critical Alerts
- [x] CEO Decisions / Tasks table
- [x] Opportunities pipeline/table
- [ ] P0/P1/P2/P3 priority engine across all departments
- [ ] 7/30/90-day goals and progress
- [ ] Cross-department conflict handling
- [ ] Approval queue with actionable approve/reject workflow
- [ ] Daily CEO Brief generator
- [ ] Weekly executive review
- [ ] Monthly executive review
- [ ] Quarterly strategic review
- [ ] Main command workflow: `شغّل الشركة`

## 2. Data Hub & Business Intelligence
- [x] PostgreSQL-based Data Hub on Google
- [x] Company metric snapshots
- [x] Alerts
- [x] Tasks
- [x] Opportunities
- [x] Salla order/product event snapshots from valid signed webhooks
- [ ] Historical KPI comparisons: today / yesterday / previous period
- [ ] Central action history across all departments
- [ ] Source status inventory: Connected / Readable / Writable / Needs Integration
- [ ] Unified company health composed from all departments, not only Technology/Voucher
- [ ] Retention policy and historical aggregation

## 3. Market & Competitor Intelligence
- [ ] Amazon.sa watchlist
- [ ] Noon Saudi watchlist
- [ ] Cobone watchlist
- [ ] Waffarha watchlist
- [ ] Google/Web/Trends watchlist
- [ ] Additional competitor watchlists defined by management
- [ ] Best Seller detection
- [ ] Rising product/category detection
- [ ] Price-change monitoring
- [ ] Offer/discount monitoring
- [ ] Market Alerts generated into Opportunities / Alerts

## 4. Product & Pricing Intelligence
- [ ] Market price range per product/category
- [ ] Demand score
- [ ] Competition score
- [ ] Pakgat Opportunity Score
- [ ] Hot classification
- [ ] Growing classification
- [ ] Slow classification
- [ ] Dormant classification
- [ ] Old classification
- [ ] Needs SEO classification
- [ ] Pricing alerts
- [ ] Post-listing price monitoring

## 5. Merchant & Supplier Acquisition
- [ ] Merchant Hunter
- [ ] Supplier Hunter
- [ ] Lead qualification
- [ ] Contacting/follow-up workflow
- [ ] Pipeline: Found → Qualified → Contacted → Replied → Negotiating → Approved → Live
- [ ] Merchant/supplier opportunity creation in Control Center
- [ ] Follow-up reminders/tasks

## 6. Growth & Commercial
- [ ] Revenue dashboard from Salla
- [ ] Orders dashboard from Salla
- [ ] Conversion rate
- [ ] AOV
- [ ] Repeat purchase
- [ ] Abandoned carts
- [ ] Promotion/discount strategy
- [ ] Cross-sell / Upsell / Bundles
- [ ] Product promotion priority recommendations
- [ ] Cart-recovery measurement

## 7. Store Operations & Merchandising
- [ ] Price-before / price-after checks
- [ ] Red Ribbon checks
- [ ] Arabic/English completeness checks
- [ ] Product image checks
- [ ] Category checks
- [ ] Homepage ordering checks
- [ ] Product metadata quality checks
- [ ] Store merchandising task queue
- [ ] Store operation alerts shown in Control Center

## 8. SEO / Google / GEO
- [ ] Google Search Console connection
- [ ] Google Analytics connection
- [ ] Organic visibility
- [ ] Keywords
- [ ] Impressions
- [ ] CTR
- [ ] Position changes
- [ ] Indexing issues
- [ ] Structured-data issues
- [ ] Meta title/description checks
- [ ] Schema / FAQ checks
- [ ] Internal linking checks
- [ ] Geo targeting checks
- [ ] Rising pages / new-page recommendations
- [ ] SEO opportunities and alerts into Control Center

## 9. Brand & Creative Studio
- [ ] Brand consistency checks
- [ ] Arabic tone of voice
- [ ] English tone of voice
- [ ] Product-image workflow
- [ ] Banner workflow
- [ ] Canva/Adobe/Image Generation workflow
- [ ] Creative briefs for campaigns/offers
- [ ] Approval requirement for sensitive/public changes

## 10. Social Media & Demand Generation
- [ ] Content calendar
- [ ] Instagram planning
- [ ] LinkedIn planning
- [ ] X planning
- [ ] Stories concepts
- [ ] Reels concepts
- [ ] Captions
- [ ] Hashtags
- [ ] Product-to-publish prioritization
- [ ] Performance measurement once source connections are available

## 11. CRM, Voucher & Customer Lifecycle
- [x] Voucher issuance
- [x] QR verification/redemption
- [x] WhatsLoop integration
- [x] Merchant notifications
- [x] Customer post-redemption messaging
- [x] Voucher status tracking
- [ ] Voucher delivery rate KPI
- [ ] Redemption rate KPI
- [ ] Failed voucher/message alerts consolidated in Control Center
- [ ] Unused voucher watch
- [ ] Win-back workflow
- [ ] Cashback monitoring
- [ ] Repeat-customer tracking
- [ ] Customer lifecycle: Order → Voucher → WhatsApp → Redemption → Return

## 12. Technology, Reliability & Security
- [x] Google Compute Engine runtime
- [x] PostgreSQL runtime on Google
- [x] Nginx + HTTPS
- [x] systemd service with auto-restart
- [x] five-minute internal monitor timer
- [x] basic app/company health endpoints
- [x] GitHub deployment history
- [ ] Full uptime monitor
- [ ] API failure monitor
- [ ] Database health monitor with thresholds
- [ ] Disk/RAM/CPU health thresholds
- [ ] Backup policy and restore test
- [ ] Security alerting
- [ ] Certificate-expiry monitoring
- [ ] Dependency/security update monitoring
- [ ] Voucher/integration failure watch consolidated into alerts
- [ ] Render references fully removed from production docs/UI/code defaults where no longer needed

## Source integrations
- [x] Voucher System
- [x] WhatsLoop runtime
- [x] Salla signed webhook reception layer
- [x] Salla event Data Hub capture
- [ ] Salla OAuth / full Merchant API connection (currently Local fallback until authorization is restored)
- [ ] Salla products full read
- [ ] Salla sales/orders historical import/read
- [ ] Salla abandoned carts
- [ ] Salla reviews
- [ ] Salla categories/inventory/home merchandising read
- [ ] Google Analytics
- [ ] Google Search Console
- [x] GitHub
- [ ] Amazon.sa
- [ ] Noon Saudi
- [ ] Cobone
- [ ] Waffarha
- [ ] Google Trends / public market sources

## Dashboard sections required by Blueprint
- [x] Executive / Company Health
- [x] Critical Alerts
- [x] CEO Decisions / Tasks
- [x] Opportunities
- [x] Voucher & CRM basic
- [x] Integrations basic
- [ ] Sales & Growth complete
- [ ] Products complete
- [ ] Market Watch complete
- [ ] Partners complete
- [ ] SEO / Google complete
- [ ] Technology complete

## Governance / authority
- [ ] AUTO actions registry: research, analysis, monitoring, reports, classifications, diagnostics, content/recommendation preparation
- [ ] APPROVAL actions registry: price change, discount, merchant/supplier outreach, add product, homepage change, campaign/public commercial change
- [ ] CEO ONLY registry: major financial agreements, commission changes, large discounts, sensitive partnerships, security/architecture changes
- [ ] Audit trail for approvals and decisions

## Operating cadence
### Daily — `شغّل الشركة`
- [ ] Read Data Hub and all available sources
- [ ] Check P0/P1 alerts
- [ ] Check market/competitors/opportunities
- [ ] Review products/prices/movement
- [ ] Review sales/conversion/carts
- [ ] Review SEO/Google
- [ ] Review partners/suppliers pipeline
- [ ] Review Voucher/WhatsApp/CRM
- [ ] Review Technology/Reliability/Security
- [ ] Generate priorities/recommendations
- [ ] Execute AUTO actions
- [ ] Produce CEO approval list
- [ ] Generate CEO Brief

### Weekly
- [ ] Compare with previous week
- [ ] Best/worst products
- [ ] Competitor movements
- [ ] Partner pipeline progress
- [ ] Next-week plan

### Monthly
- [ ] Full growth report
- [ ] Department performance
- [ ] What worked / failed
- [ ] Goal update
- [ ] Next-month plan

### Quarterly
- [ ] Categories strategy
- [ ] Competition strategy
- [ ] Technology/cost review
- [ ] Expansion review

## KPI coverage required by Blueprint
- [ ] Growth: Revenue, Orders, Conversion Rate, AOV, Repeat Purchase, Cart Recovery
- [ ] Acquisition: Organic Traffic, Paid/Direct Mix, Search Impressions, CTR, Keyword Positions
- [ ] Products: Sell-through, Time-to-first-sale, Slow/Dormant Count, Price Competitiveness, Opportunity Score
- [ ] Merchants: Qualified Leads, Contact Rate, Reply Rate, Negotiation Rate, Signed/Live Offers
- [ ] Voucher: Issued, Delivered, Redeemed, Redemption Rate, Failures, Time-to-delivery
- [ ] WhatsApp: Sent, Delivered, Failed, response metrics when available
- [ ] Store Ops: Products needing update, missing EN, pricing issues, merchandising tasks completed
- [ ] Technology: Uptime, Error Rate, Failed Jobs, DB/API Health, unresolved critical issues
- [ ] Execution: Tasks completed, overdue tasks, decision turnaround time, automation success rate

## Non-negotiable architecture decision
- Google Cloud is the production runtime and monitoring platform.
- GitHub remains source control/deployment history.
- Render is not a required runtime dependency and must not be reintroduced.

## Current implementation checkpoint — 19 Aug 2026
Implemented foundation: Google runtime, PostgreSQL, Voucher/QR/WhatsLoop, Control Center, Company Health, Data Hub tables, five-minute monitor, alerts/tasks, opportunities, Salla webhook Data Hub capture.

Next implementation order:
1. Finish Salla business data and OAuth/full read connection.
2. Sales & Growth + Products dashboard sections.
3. SEO/Search Console/Analytics.
4. Market & Competitor Intelligence + Product/Pricing Watch.
5. Merchant/Supplier pipeline.
6. Store Operations & Merchandising checks.
7. CRM retention/unused voucher/cashback/repeat customer intelligence.
8. Technology reliability/security depth and backups.
9. Brand/Creative/Social workflows.
10. Daily `شغّل الشركة`, CEO Brief, approvals, weekly/monthly/quarterly operating cadence.
