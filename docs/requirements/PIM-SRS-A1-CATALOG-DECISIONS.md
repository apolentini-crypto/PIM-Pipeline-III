# Amendment A1 to CT-PIM-SRS-001 — Catalog Decisions (Stage 2b)

| | |
|---|---|
| **Document ID** | `CT-PIM-SRS-001-A1` |
| **Version** | 0.2 — **APPROVED by operator 2026-10-18 (D-8)**; OQ-21 terminus open |
| **Date** | 2026-10-18 |
| **Amends** | `CT-PIM-SRS-001` v1.0 (Baselined 2026-08-19) |
| **Status** | Approved. To be folded into the SRS per its convention (**[AMENDED]** in place, logged in §12) at the next SRS revision. |
| **Author** | Claude (Cowork) under operator direction, 2026-10-18 |
| **Numbering** | Continues the SRS: `FR-140+`, `AC-33+`, `OQ-20+`, `D-8+` (proposed), gates `G-DECIDED` etc. |

---

## 0. Why this amendment exists

The baseline covers two of the operator's three phases completely:

| Operator phase (2026-10-18, verbatim intent) | Baseline coverage |
|---|---|
| **Phase 1** — "build up information on a brand across all its products until complete" | Stages 1–2, FR-6..26. Complete. |
| **Phase 2** — "downselect products the store will carry … derived skus, pricing, counts, changes to title/description" | **Absent.** The SRS has hold (FR-46) and exclusion (FR-45) but no affirmative carry decision, no derivative rows, no SKU construction beyond "a SKU rule exists" (FR-2), no pricing rules, no quantity or fulfillment state, no customs fields. |
| **Phase 3** — "specific changes to send to my store via the api … custom fields, customs, quantities, pricing, html" | Stages 3–5, FR-27..130. Complete except customs (FR-164..166 below). |

The second-generation tool (PIM2, June–July 2026) had every Phase-2 element — `decisions`
(sell-as, fulfillment, category, SKU override, interim price), `derivatives` (pack
quantity, markup), `pricing_rules` (scope, markup, rounding), customs push — and nothing
after it carried them forward. This amendment restores them **as requirements**, under the
baseline's own rules: declared not coded (D-6), reversible (FR-25/26), visible before write
(FR-74), nothing unwritable (FR-48).

**Operator rulings 2026-10-18:**
- **D-8 (proposed id)** — amendment approved ("Yes"), with the SKU grammar fixed in FR-150.
- Edit surface is the CSV round trip first (FR-137..139), a browser view later if needed.
- Brand #2 is **Pace Worldwide** (OQ-25).


---

## 1. Definitions (additions to SRS §2)

| Term | Meaning |
|---|---|
| **Canonical row** | (unchanged) one normalised record per **vendor MPN** — the merge output |
| **Catalog row** | one record per **CT SKU** that the store may carry: a carried canonical row, or a **derivative** of one. Derivation (Stage 3) runs on catalog rows. |
| **Decision** | An operator-authored record about a canonical row: carry state, fulfillment, category, price basis, quantity, derivatives. Stored separately from overrides because it is not a correction of vendor data; governed by the same reversibility and pre-value rules. |
| **Carry state** | `undecided` · `carry` · `derivatives-only` · `carry+derivatives` · `skip`. `hold` (FR-46) and exclusion (FR-45) are unchanged and orthogonal. |
| **Derivative** | A catalog row sold in a different count than the vendor sells it (a 10-count cut from a 100-count), keyed `(parent MPN, pack_qty)`. |
| **Pricing rule** | A declared formula that yields a price for rows in a scope (brand, category, derivative, row), with rounding. |
| **CT SKU** | The store's SKU for a catalog row, built by the brand pack's declared SKU rule or set by operator override. |

---

## 2. Placement — Stage 2b

```
Stage 1  INGEST            vendor files → raw frames
Stage 2  NORMALISE+MERGE   → canonical rows (1 per MPN) → aliases → units → overrides
Stage 2b DECIDE  (NEW)     decisions × canonical rows → catalog rows (1 per CT SKU)
Stage 3  DERIVE            facets · packing · SEO · families · HTML — on CATALOG rows
Stage 4  STORE             SQLite + canonical export; CSV round trip
Stage 5  PUBLISH           unchanged; terminus per OQ-21
```

Stage 2b sits after overrides and before derivation so that a derivative row receives
facets, SEO strings and packed spec fields exactly as an original does. Stages 1–2 and
Stage 5 are untouched by this amendment.

---

## 3. Functional requirements

### 3.1 Carry state

- **FR-140** Every canonical row shall carry exactly one **carry state** from the declared
  set `{undecided, carry, derivatives-only, carry+derivatives, skip}`, defaulting to
  `undecided` on first appearance.
- **FR-141** A row in state `undecided` or `skip` shall produce **no catalog row** and shall
  never reach Stage 5; the build report shall state the count per carry state, with the
  `undecided` count first.
  > *Rationale: the first-generation load published every row that merged. The operator's
  > stated Phase 2 is a downselect; the default must be "not yet", never "yes".*
- **FR-142** A canonical row that disappears from every source while holding a non-default
  carry state shall be **reported by MPN on every build** and its decision retained; it
  shall never be silently dropped.
  > *Rationale: FR-45's reasoning in reverse — a decision that vanishes with a vendor file
  > change is invisible loss.*
- **FR-143** Carry state shall be **independent of** hold (FR-46) and exclusion (FR-45): a
  carried row may be held; an excluded row is removed remotely whatever its carry state.

### 3.2 Derivatives

- **FR-144** The system shall support **derivative declarations** per canonical row: a
  positive integer `pack_qty`, an optional name, description, category and pricing basis;
  each declaration yields one catalog row keyed `(parent MPN, pack_qty)`.
- **FR-145** A derivative row shall **inherit every field of its parent** unless the
  declaration overrides it; the inherited value's provenance shall record `inherited(parent
  MPN, field)` so the source cell is still reachable (FR-47).
- **FR-146** Pack arithmetic shall be **declared, not assumed**: a derivative's unit-based
  values (cost per unit, weight per unit) may be computed **only** from a parent field the
  pack declares as per-unit or as a count (`PACKAGE QTY`), with the formula recorded as the
  value's provenance. Where the declaration is absent the value is **omitted**, never
  divided.
  > *Rationale: the standing rule "never divide a PACK figure by a quantity" (gen-1 FINDINGS
  > §14) — a 10-pack carton measures ~14 units by volume and the quantity column was once
  > flattened to 1. Carton dimensions never divide; only declared per-unit quantities multiply.*
  > *Operator ruling 2026-10-20 (Lindström spatulas, PACKAGE QTY = 1000): "those are package
  > quantities that the factory purchases (inbound to factory). All items are purchased by
  > distributors as each." ⇒ the pack declares `purchase_unit: each` (the default); vendor pack
  > columns are never read for arithmetic; a derivative of qty N costs N × cost-per-each.*
- **FR-144a [ADDED 2026-10-20]** A derivative may also be a **kit**: a declared list of
  components `(MPN, qty)` under an **operator-assigned MPN** (SKU `{brand}.{kit-mpn}`, no
  `.P` ending). Cost and weight are the sums of the components' per-each values; name,
  description, dimensions and images are operator-supplied or inherited from the first
  component by declaration. *Example: `59.MS-KIT5` = MSEF + MSF×2 + MSM + MSL.*
- **FR-147** A derivative's **physical dimensions** shall be operator-supplied or omitted;
  the system shall never compute them from the parent's.
- **FR-148** A derivative whose parent is not in state `derivatives-only` or
  `carry+derivatives` shall be a **build failure naming parent and pack_qty**, never a
  silent skip.
- **FR-149** A derivative shall be a catalog row in every respect: derived (Stage 3),
  stored, exported, published, verified and rolled back by the same mechanisms as an
  original, with no special-casing in code.

### 3.3 CT SKU construction

- **FR-150 [RULED D-8, 2026-10-18]** Every catalog SKU shall conform to the store-wide
  grammar, declared once as data (not per brand) and validated at the input boundary:

  ```
  {brand}.{mpn}[-{cond}][.{ending}]
     brand   = the BigCommerce brand id (digits)
     mpn     = normalised vendor part number
     -cond   = optional condition on the part number (e.g. -U used), dash, BEFORE any ending
     .ending = optional, exactly one of:
                 M        master listing            2.53131A.M
                 <n>      one serialized unit       2.53131A.1   2.53131A-U.1
                 P<qty>   a pack of qty             2.53131A.P3
  ```
  Dots between every part; **never a dash after the brand number.** The brand pack
  declares only the **MPN normalisation** (case, whitespace, permitted character class,
  trim set) and the brand id. Code contains no grammar text (D-6): the grammar lives in a
  store-level declaration the parser and validator read.
  > *Operator, 2026-10-18 (verbatim): "`brand.mpn` is the base, and an optional ending `.x`
  > can follow … A condition goes on the part number with a dash, before any dot ending …
  > All dots between the parts, never a dash after the brand number."*
- **FR-150a** The SKU parser shall be a **single function** shared by every consumer
  (validation, derivative construction, endpoint matching, the Hub's child-of-master
  resolver pattern), and shall reject any SKU that does not parse, naming the rule broken.
  No fuzzy matching.
- **FR-151** The operator shall be able to **override the SKU** of any catalog row with a
  recorded basis; clearing the override restores the rule-built SKU (FR-26 semantics).
- **FR-152** **G-SKU-UNIQUE**: before any publish, every catalog SKU shall be unique within
  the brand, across all brands in the store, and against the endpoint's existing SKUs
  (FR-61); a collision halts naming both rows.
- **FR-153** A SKU that the ledger records as published shall be **immutable through the
  build**; changing it is a distinct, armed, ledgered `rename` operation (FR-72 table gains
  `rename`), because channel systems key on SKU and a rename propagates to marketplaces.
  > *Rationale: the 2026-06-24 BC rename spec §8 — renames re-sync to eBay/Walmart.*

### 3.4 Pricing

- **FR-154** The brand pack shall declare **pricing rules** with a scope from
  `{row, derivative, category, brand, default}`, a basis from `{markup-on-cost,
  discount-off-msrp, fixed, msrp-passthrough}`, a factor, and a rounding rule
  (e.g. `.95`, `.99`, `none`, `nearest-cent`). Scopes resolve most-specific first.
- **FR-155** The effective price of a catalog row shall resolve in the declared order:
  operator-set price (decision) → most specific matching rule → MSRP passthrough if
  declared → **unpriced**. The resolution step taken shall be the price's provenance.
- **FR-156** An **unpriced** catalog row shall carry an explicit state and shall never
  publish a price of `0` by inference; the pack declares what unpriced means at the endpoint
  (e.g. `is_price_hidden` + `availability: disabled`, FR-122) or that it is held (FR-46).
  *(Closes OQ-13: absence is always an explicit state, never inferred.)*
- **FR-157** The system shall compute and report **margin** (price, cost, margin %) per
  catalog row and shall flag rows below a declared floor; the flag is reported, never
  enforced by refusing a write (P2).
- **FR-158** Pricing rules shall be ordinary pack data: changing one and rebuilding
  recomputes every affected price, and the resulting change set is subject to blast-radius
  and directional-anomaly checks (FR-80..82) exactly like any other field.
- **FR-159** Price, cost, MSRP and sale price remain **ordinary managed fields** (FR-51).
  This section adds how a price is *derived*; it adds no privilege and no exclusion.

### 3.5 Quantity and fulfillment

- **FR-160** Every catalog row shall carry a **fulfillment** value from a pack-declared
  vocabulary (e.g. `stock`, `factory-order`, `drop-ship`) and an optional **initial
  quantity**.
- **FR-161** The endpoint adapter's declarations shall map fulfillment to endpoint fields
  (inventory tracking mode, availability text, lead-time custom field); core shall contain
  no such mapping.
- **FR-162** Quantity shall be written **on create only** by default; after the first
  publish it is **unmanaged** (FR-53/57) unless the pack declares otherwise, so live stock
  is never overwritten by a rebuild. Drift is reported every run (FR-57).
- **FR-163** The initial quantity of a derivative shall be independent of its parent's.

### 3.6 Customs

- **FR-164** The canonical row shall support **country of origin** (ISO-3166-1 alpha-2) and
  **HS tariff code** as ordinary fields, with the country-name→ISO2 table and the HS
  normalisation rule (strip non-digits, strip trailing zero padding, even length ≥ 6)
  declared in the pack; the raw vendor value is retained alongside.
- **FR-165** The BigCommerce adapter's `capabilities()` shall declare the customs
  sub-resource (`PUT /v3/shipping/products/customs-information`, batch ≤ 50, keyed by
  product id) and reconcile it by product id like any other sub-resource (FR-63). *If the
  terminus is the Hub (OQ-21), the canonical import contract carries the same two fields.*
- **FR-166** Commodity description for customs shall be the product name truncated to the
  declared endpoint limit; truncation here is permitted **only** because it is a declared
  endpoint field with no filter or display role (an explicit exception to FR-34, logged).

### 3.7 Content edits

- **FR-167** Title, description, meta description and search-keyword rewrites are
  **overrides** (FR-25/26) on the catalog row; no new mechanism. The truth rules FR-131..134
  apply to operator copy exactly as to vendor copy.
- **FR-168** Description HTML shall be sanitised to a **pack-declared tag whitelist** (gen-1
  contract: `p ul ol li strong em h3 h4 br`; unwrap `div span section a`; delete `script
  style iframe`), with vendor `h1/h2` mapped to `h3`; the whitelist is data.
- **FR-169** A derivative's name and description shall default to the parent's with the
  pack-declared count phrase composed in (`compose` rule, FR-115), so a 10-count never
  carries the parent's "100 pcs" claim.

### 3.8 Decision surface and persistence

- **FR-170** Decisions shall persist in the brand pack as **`decisions/`** data (CSV or
  YAML), one row per MPN, plus a derivatives table keyed `(MPN, pack_qty)`; they shall
  survive every rebuild and be diffable and version-controllable.
- **FR-171** The system shall export a **decision sheet** per brand — one row per canonical
  MPN with the vendor identity columns, current carry state, fulfillment, category, cost,
  MSRP, resolved price, margin, derivative summary — through FR-137, and import edits
  through FR-138 so every decision change is diffed, blast-radius-checked and reversible.
- **FR-172** A decision shall carry a **pre-value guard** (FR-25 semantics) on the vendor
  fields it was made against where declared (default: cost and MSRP): if those moved since
  the decision, the build **reports** the stale decision; it halts only where the pack
  declares the guard blocking.
  > *Rationale: a price decision taken against last year's cost is the §9.13 signature in
  > miniature; but refusing every build for every cost change would make the layer unusable.
  > Report by default, block by declaration.*
- **FR-173** Every decision record shall carry a basis (who, when, why) and shall be
  removable, restoring the default state (`undecided`, no derivatives, rule pricing).

### 3.9 Gates (additions to SRS §7.4)

| Gate | Assertion | Requirement |
|---|---|---|
| **G-DECIDED** | zero `undecided` rows in the publish set; counts per state reported | FR-141 |
| **G-SKU-UNIQUE** | catalog SKUs unique in brand, store and endpoint | FR-152 |
| **G-PRICE** | every catalog row has a resolved price or an explicit unpriced state | FR-155, FR-156 |
| **G-DERIV** | every derivative has a parent in a derivative-permitting state; pack arithmetic has declared inputs | FR-146, FR-148 |
| **G-STALE-DECISION** | stale decisions reported (blocking only where declared) | FR-172 |

Each gate ships with a corruptor fixture that turns it red (FR-87, AC-17).

---

## 4. Data model additions (SRS §6)

**§6.1 — new groups on the catalog row** (open set, D-6 unchanged):

| Group | Fields |
|---|---|
| Decision | carry state, fulfillment, initial quantity, price basis, decision basis |
| Lineage | parent MPN, pack_qty (derivatives), inherited-field set |
| Customs | country of origin (ISO2), HS code (normalised), raw vendor values |

**§6.2 — brand pack additions**

```
brands/<brand>/
  pricing.yaml          pricing rules: scope, basis, factor, rounding, margin floor
  decisions/            carry states, fulfillment, quantities, price overrides (CSV/YAML)
  derivatives.csv       parent MPN, pack_qty, overrides
  sku.yaml              SKU template + MPN normalisation (may fold into brand.yaml)
  customs.yaml          country-name→ISO2 table, HS normalisation rule
```

**Store (ADR-2 schema):** `decisions(brand, mpn, …)`, `derivatives(brand, mpn, pack_qty, …)`,
`catalog_rows(build_id, sku, mpn, pack_qty)`; `field_values` and `rows` key on **catalog
SKU** from Stage 2b onward.

---

## 5. Acceptance criteria (additions)

- **AC-33** A brand with 300 canonical rows and 40 carried produces exactly 40 catalog rows
  plus declared derivatives; the build names the 260 non-carried by state.
- **AC-34** Declaring a 10-count derivative of a 100-count parent yields a catalog row with
  rule-built SKU, inherited facets, composed name, computed unit cost **only** where the
  parent declares `PACKAGE QTY`, omitted dimensions, and provenance on every field.
- **AC-35** Changing one pricing rule's factor and rebuilding changes exactly the rows in its
  scope; the change set reports count, magnitude and direction before any write.
- **AC-36** A SKU collision between two brands, and between a build and the endpoint, each
  halt naming both rows.
- **AC-37** A decision whose MPN leaves the vendor file is reported on three consecutive
  builds and never deleted.
- **AC-38** The decision sheet round-trips losslessly (AC-29 semantics): export → import
  unmodified → empty change set; export → change 20 carry states → import → exactly 20
  decision changes, each individually removable.
- **AC-39** Customs fields publish and verify like any field; a row with no country of
  origin writes no customs record and says so.
- **AC-40** Every new gate in §3.9 is demonstrated red on its corruptor fixture.

---

## 6. Open questions (continue SRS §11.2)

| ID | Question | Default if unruled | Owner |
|---|---|---|---|
| ~~**OQ-20**~~ | **CLOSED by D-8 (operator, 2026-10-18)** — grammar `{brand}.{mpn}[-{cond}][.{M\|n\|P<qty>}]`, see FR-150. | — | — |
| **OQ-20b** | **Lindström rename.** All 346 live `59-<mpn>` SKUs violate D-8 ("never a dash after the brand number"). Rename to `59.<mpn>` is a `rename` operation (FR-153): armed, ledgered, dry-run first, with the marketplace re-sync caution of the 2026-06-24 rename spec §8. **When?** Before M6 migration (so the pack reproduces live under the correct grammar) or as its own run after? | Plan it as the first operation of M6; do not run without an explicit operator "go" | Operator |
| **OQ-21** | **Terminus.** Hub ruling 2026-08-03: loads terminate at the Hub. SRS 2026-08-19: direct BC adapter. Which stands, and when does the canonical import contract land? | Build Stage 5 behind the adapter protocol (already required); BC adapter first, Hub-door adapter when the contract exists | Hub Design (ask sent 2026-10-18) |
| **OQ-22** | Derivative dimensions: always operator-supplied, or allow a declared packaging table (pack_qty → box size)? | Operator-supplied or omitted (FR-147) | Operator |
| **OQ-23** | Pricing rule scope set: is `{row, derivative, category, brand, default}` sufficient, or is a cost-band scope needed (e.g. markup by cost tier)? | As listed | Operator |
| **OQ-24** | Stale-decision guard default: report-only, or blocking for price decisions specifically? | Report-only; blocking declared per pack | Operator |
| **OQ-25** | Brand #2 = **Pace Worldwide** (operator 2026-10-18). Sources, counts and image situation not yet inventoried; needed before M2 hardens the rule vocabulary (ARCH §14). | — | Operator |

---

## 7. Traceability

| Operator phrase (2026-10-18) | Requirement |
|---|---|
| "Decide which items will be put into my store" | FR-140..143, G-DECIDED |
| "derivatives (new) items … take a 100 ct item and sell 10ct items" | FR-144..149, G-DERIV |
| "Add my own sku based on the sku design" | FR-150..153, G-SKU-UNIQUE, OQ-20 |
| "Change information such as Description, formatting, title" | FR-167..169 |
| "Finalize my pricing, quantities, etc" | FR-154..163, G-PRICE |
| "custom fields per castletronics requirements" | unchanged — FR-27..35, FR-112..118 |
| "customs information" | FR-164..166 |
| "filter products on the site (see Lindstrom)" | unchanged — FR-27..31, Appendix A |
| "Phase 1 / 2 / 3" | Stages 1–2 / 2b / 3–5 (§2) |

*End of CT-PIM-SRS-001-A1 v0.2 (approved 2026-10-18).*
