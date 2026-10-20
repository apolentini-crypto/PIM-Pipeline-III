"""Brand-pack models (SRS §6.2 + A1 §4; ADR-4).

Every file in a brand pack has a model here. ``extra="forbid"`` so a typo'd key fails
loud (P3, AC-27). JSON Schemas are generated from these into docs/schemas/.

These models describe the SHAPE of declarations. They enumerate no brand, no field
name, no count and no format of product data (D-6): a brand with 30 fields and one with
300 use the same models.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


# --------------------------------------------------------------------------- brand.yaml
class MpnNormalisation(Strict):
    upper: bool = True
    strip_whitespace: bool = True
    replace: dict[str, str] = Field(default_factory=dict)
    allowed: Optional[str] = Field(default=None, description="regex character class, e.g. A-Z0-9_-")
    trim: Optional[str] = Field(default=None, description="characters stripped from both ends")


class Environment(Strict):
    kind: Literal["sandbox", "live"]
    store_hash_env: str = Field(description="name of the env var holding the store hash (never the value, NFR-14)")
    token_env: str = Field(description="name of the env var holding the API token (never the value)")


class Brand(Strict):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str
    bc_brand_name: str = Field(description="exact brand name as it exists in BigCommerce; resolved to an id at run time")
    brand_id: Optional[int] = Field(default=None, description="BigCommerce brand id = SKU prefix. None until the brand exists in BC.")
    mpn_normalisation: MpnNormalisation = Field(default_factory=MpnNormalisation)
    text_fixes: dict[str, str] = Field(default_factory=dict, description="FR-24/132: declared codepoint corrections applied to every text value, e.g. {'º': '°'}; each application is noted")
    environments: dict[str, Environment] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_live_default(self):
        if "default" in self.environments:
            raise ValueError("an environment named 'default' is forbidden: every run names its environment (FR-5)")
        return self


# --------------------------------------------------------------------------- sources.yaml
class Block(Strict):
    """One keyed block inside a sheet (FR-12). Columns are exact header text (FR-111)."""
    id: str
    key_column: Optional[str] = None
    key_index: Optional[int] = Field(default=None, ge=1, description="1-based column index of the key when its header is blank")
    col_from: Optional[int] = Field(default=None, ge=1, description="1-based first column of the block")
    col_to: Optional[int] = Field(default=None, ge=1, description="1-based last column of the block (inclusive)")
    columns: Optional[list[str]] = Field(default=None, description="restrict to these headers; None = all in range")

    @model_validator(mode="after")
    def _key(self):
        if not self.key_column and not self.key_index:
            raise ValueError(f"block {self.id!r}: declare key_column or key_index")
        return self


class Source(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    path: str = Field(description="relative to the pack's declared source_root, or absolute")
    format: Literal["xlsx", "xlsm", "csv", "json"]
    sheet: Optional[str] = None
    header_row: int = Field(default=1, ge=1, description="1-based row holding the headers")
    key_column: Optional[str] = Field(default=None, description="exact header of the join key; required unless blocks or key_index are declared")
    key_index: Optional[int] = Field(default=None, ge=1, description="1-based column index of the key when its header is blank")
    blocks: list[Block] = Field(default_factory=list)
    optional: bool = Field(default=False, description="FR-13: proceed with a recorded warning when absent")
    multi: bool = Field(default=False, description="long format: many rows per key (e.g. one row per image); fields select with a `where`")
    flatten: list[str] = Field(default_factory=list, description="json: nested dict keys exposed as 'parent.child' columns")
    max_cols: Optional[int] = Field(default=None, ge=1, description="bound the read for sheets with phantom columns")
    encoding: str = Field(default="utf-8-sig", description="csv/json text encoding, declared (e.g. cp1252 for a Windows-saved CSV)")
    typed_columns: dict[str, Literal["number", "date"]] = Field(default_factory=dict, description="FR-8: everything else is read as text")

    @model_validator(mode="after")
    def _key_or_blocks(self):
        if not self.key_column and not self.key_index and not self.blocks:
            raise ValueError(f"source {self.id!r}: declare key_column, key_index or at least one block")
        if self.format in ("xlsx", "xlsm") and not self.sheet and not self.blocks:
            raise ValueError(f"source {self.id!r}: xlsx/xlsm sources must name a sheet (readers are declared, not sniffed — FR-7)")
        return self


class Sources(Strict):
    source_root: str = Field(description="folder the relative source paths resolve against; READ-ONLY (FR-10)")
    sources: list[Source] = Field(min_length=1)

    @field_validator("sources")
    @classmethod
    def _unique_ids(cls, v):
        ids = [s.id for s in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate source ids: {dupes}")
        return v


# --------------------------------------------------------------------------- joins.yaml
class KeyRule(Strict):
    rule: Literal["trim-only", "upper-trim", "declared-normalisation"] = "trim-only"


class Association(Strict):
    """FR-16: explicit code→code mapping. from_* = the other source and ITS code; to_* = the primary
    source and the roster key that code belongs to. Always wins over computed matches."""
    from_source: str
    from_key: str
    to_source: str
    to_key: str
    basis: str = Field(description="who/when/why — never leave an association unexplained")


class Joins(Strict):
    key: KeyRule = Field(default_factory=KeyRule)
    primary_source: str = Field(description="the source whose key set defines the roster of canonical rows")
    associations: list[Association] = Field(default_factory=list)


# --------------------------------------------------------------------------- fields.yaml
class ColumnRef(Strict):
    source: str
    column: str = Field(description="exact header text, byte-for-byte (FR-111)")
    block: Optional[str] = Field(default=None, description="block id when the source declares blocks")
    where: Optional[dict[str, str]] = Field(default=None, description="multi sources: pick the row whose columns equal these values")
    unit: Optional[str] = Field(default=None, description="unit the COLUMN HEADER carries (e.g. 'Length (mm)' -> mm), used when a value is a bare number; a unit inside the value still wins")


class UnitSpec(Strict):
    parse: Literal["in-value", "declared"] = "declared"
    expect: list[str] = Field(default_factory=list, description="unit tokens accepted, e.g. [mm, in]")
    unit: Optional[str] = Field(default=None, description="for parse=declared: the unit the column carries")
    decimal_comma: bool = False


class FieldDecl(Strict):
    primary: ColumnRef
    aliases: list[ColumnRef] = Field(default_factory=list, description="FR-18: fire only when primary is empty")
    alias_tolerance: Optional[str] = Field(default=None, description="FR-20: numeric tolerance like '2%' or '0.5'; absent = exact")
    unit: Optional[UnitSpec] = None
    type: Literal["text", "number", "integer", "bool", "html", "url"] = "text"
    confirmed: Literal["Y", ""] = Field(default="", description="FR-105: 'Y' publishes the field; blank leaves it out")
    required: bool = Field(default=False, description="INV-17: absence is a build failure, not an empty value")


class Fields(Strict):
    fields: dict[str, FieldDecl] = Field(min_length=1, description="canonical field name → declaration; the set is OPEN (D-6)")

    @field_validator("fields")
    @classmethod
    def _names(cls, v):
        bad = [k for k in v if not k.replace("_", "a").isalnum() or k != k.lower()]
        if bad:
            raise ValueError(f"canonical field names must be lower_snake_case: {bad}")
        return v


# --------------------------------------------------------------------------- derive.yaml (ADR-5 rule vocabulary)
class RuleCopy(Strict):
    rule: Literal["copy"]
    input: str


class RuleMap(Strict):
    rule: Literal["map"]
    input: str
    values: dict[str, str]
    else_: Optional[str] = Field(default=None, alias="else")
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RuleSlug(Strict):
    rule: Literal["slug"]
    input: str


class Band(Strict):
    lt: Optional[str] = None
    else_: Optional[bool] = Field(default=None, alias="else")
    value: str
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RuleBand(Strict):
    rule: Literal["band"]
    input: str
    bands: list[Band] = Field(min_length=1)
    boundary: Literal["lower-inclusive", "upper-inclusive"] = Field(description="FR-28: which side a boundary value joins — declared, never defaulted silently")
    display_pair: Optional[str] = Field(default=None, description="FR-114: emit X_disp from this raw field")


class RulePrecedence(Strict):
    rule: Literal["precedence"]
    of: list[str] = Field(min_length=2, description="A ELSE B ELSE C — never both")


class RuleSkuPattern(Strict):
    rule: Literal["sku-pattern"]
    input: str = "mpn"
    patterns: list[dict[str, str]] = Field(description="[{match: '^RX', value: ergo}, ...] anchored regexes, first wins")
    else_: Optional[str] = Field(default=None, alias="else")
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RuleCompose(Strict):
    rule: Literal["compose"]
    format: str = Field(description="format string over canonical fields, e.g. '{length_mm} mm / {length_in} in'")
    omit_if_missing: list[str] = Field(default_factory=list, description="FR-35: if any of these is empty, emit nothing")


class RulePack(Strict):
    rule: Literal["pack"]
    keys: list[str] = Field(min_length=1, description="declared key order (FR-32, FR-117 append-only)")
    pair_separator: str = "="
    item_separator: str = ";"
    max_length: Optional[int] = Field(default=None, description="FR-34: halt, never truncate")
    overflow_field: Optional[str] = None
    vocabulary_exempt: list[str] = Field(default_factory=list, description="display-only keys like cap_disp")


class RuleFamily(Strict):
    rule: Literal["family"]
    by: str = Field(description="canonical field whose equal values form a family (e.g. product_block)")
    union: Optional[str] = Field(default=None, description="path of a declared twins CSV")
    order: Literal["mpn-numeric", "mpn-text", "declared"] = "mpn-numeric"


Rule = Annotated[
    Union[RuleCopy, RuleMap, RuleSlug, RuleBand, RulePrecedence, RuleSkuPattern, RuleCompose, RulePack, RuleFamily],
    Field(discriminator="rule"),
]


class FacetScope(Strict):
    chapters: list[str] = Field(description="FR-29: categories where this facet must be present")
    absent_in: list[str] = Field(default_factory=list, description="FR-29: categories where it must be absent")
    filtering: bool = Field(default=False, description="FR-113: a blank filtering key is a blocking failure")


class Derive(Strict):
    facets: dict[str, Rule] = Field(default_factory=dict)
    scopes: dict[str, FacetScope] = Field(default_factory=dict)
    display: dict[str, Rule] = Field(default_factory=dict, description="spec display strings (compose)")
    packed: dict[str, RulePack] = Field(default_factory=dict, description="packed custom fields, e.g. filter_metadata, spec_display")
    families: dict[str, RuleFamily] = Field(default_factory=dict)
    seo: dict[str, RuleCompose] = Field(default_factory=dict)
    page_type_value: Optional[str] = Field(default=None, description="FR-121 ct_page_type; absent ⇒ default archetype")


# --------------------------------------------------------------------------- vocabulary.json
class Vocabulary(Strict):
    version: str
    facets: dict[str, list[str]] = Field(description="facet key → frozen allowed slugs (FR-30)")

    @field_validator("facets")
    @classmethod
    def _slugs(cls, v):
        import re
        bad = {k: [x for x in vals if not re.match(r"^[a-z0-9][a-z0-9-]*$", x)] for k, vals in v.items()}
        bad = {k: b for k, b in bad.items() if b}
        if bad:
            raise ValueError(f"vocabulary values must be slugs ^[a-z0-9][a-z0-9-]*$: {bad}")
        return v


# --------------------------------------------------------------------------- expectations.yaml
class Expectations(Strict):
    roster_count: Optional[int] = Field(default=None, ge=0)
    per_chapter: dict[str, int] = Field(default_factory=dict)
    tolerance: int = Field(default=0, ge=0, description="rows of slack before an expectation fails")


# --------------------------------------------------------------------------- managed.yaml
class Managed(Strict):
    managed: Union[Literal["all-mapped"], list[str]] = "all-mapped"
    unmanaged: list[str] = Field(default_factory=list, description="FR-57: drift-reported, never written this run")
    owners: dict[str, str] = Field(description="owner component → list is reversed at load; here field-group → owner (FR-54..56)")


# --------------------------------------------------------------------------- thresholds.yaml
class Threshold(Strict):
    max_rows_fraction: float = Field(default=0.25, ge=0, le=1, description="OQ-6 default: >25% of rows changing needs typed confirmation")
    max_direction_fraction: float = Field(default=0.80, ge=0.5, le=1, description="OQ-6 default: >80% of changes same direction = directional anomaly")
    max_rows_absolute: Optional[int] = None


class Thresholds(Strict):
    default: Threshold = Field(default_factory=Threshold)
    per_field: dict[str, Threshold] = Field(default_factory=dict)


# --------------------------------------------------------------------------- endpoints.yaml
class EndpointBinding(Strict):
    adapter: str = Field(description="registered adapter name, e.g. bigcommerce, csvexport, hub-door")
    environments: list[str] = Field(min_length=1, description="names from brand.yaml environments")
    field_map: dict[str, str] = Field(default_factory=dict, description="canonical field → endpoint field (FR-104)")
    sentinel_empty_fields: list[str] = Field(default_factory=list, description="FR-65: write explicit empties, e.g. related_products")
    custom_fields: list[str] = Field(default_factory=list, description="packed/derived fields emitted as custom fields")


class Endpoints(Strict):
    endpoints: dict[str, EndpointBinding] = Field(min_length=1)


# --------------------------------------------------------------------------- pricing.yaml (A1 FR-154..159)
class PricingRule(Strict):
    scope: Literal["default", "brand", "category", "derivative", "row"]
    scope_value: Optional[str] = Field(default=None, description="category name / mpn / (mpn,pack_qty) as 'MPN.P10'; None for default/brand")
    basis: Literal["markup-on-cost", "discount-off-msrp", "fixed", "msrp-passthrough"]
    factor: Optional[float] = Field(default=None, description="0.35 = 35% markup or 35% discount; the fixed price for basis=fixed")
    rounding: Literal["none", "nearest-cent", ".95", ".99", "whole-dollar"] = "nearest-cent"
    basis_note: str = Field(default="", description="who/when/why")

    @model_validator(mode="after")
    def _factor_needed(self):
        if self.basis != "msrp-passthrough" and self.factor is None:
            raise ValueError(f"pricing rule scope={self.scope} basis={self.basis}: factor is required")
        if self.scope in ("category", "derivative", "row") and not self.scope_value:
            raise ValueError(f"pricing rule scope={self.scope}: scope_value is required")
        return self


class Pricing(Strict):
    rules: list[PricingRule] = Field(default_factory=list)
    margin_floor_pct: Optional[float] = Field(default=None, description="FR-157: flag (never refuse) rows below this margin")
    unpriced_means: Literal["hold", "price-hidden"] = Field(default="hold", description="FR-156: explicit meaning of 'no price'")
    fulfillment_vocabulary: list[str] = Field(default_factory=lambda: ["stock", "factory-order"], description="FR-160")


# --------------------------------------------------------------------------- overrides/*.yaml (FR-25/26)
class OverrideBasis(Strict):
    who: str
    when: str
    why: str


class Override(Strict):
    sku: str = Field(description="roster key (vendor MPN) the override applies to")
    field: str
    before: Optional[str] = Field(default=None, description="FR-25: the value the build produced when this override was written; None = field was empty")
    after: Optional[str] = Field(default=None, description="None = clear the field")
    basis: OverrideBasis


class OverrideFile(Strict):
    overrides: list[Override] = Field(default_factory=list)


# --------------------------------------------------------------------------- the whole pack
PACK_FILES: dict[str, tuple[type[BaseModel], bool]] = {
    # file name → (model, required)
    "brand.yaml": (Brand, True),
    "sources.yaml": (Sources, True),
    "joins.yaml": (Joins, True),
    "fields.yaml": (Fields, True),
    "derive.yaml": (Derive, False),
    "vocabulary.json": (Vocabulary, False),
    "expectations.yaml": (Expectations, False),
    "managed.yaml": (Managed, True),
    "thresholds.yaml": (Thresholds, False),
    "endpoints.yaml": (Endpoints, True),
    "pricing.yaml": (Pricing, False),
}
PACK_DIRS = ("overrides", "decisions")
PACK_OPTIONAL_CSV = ("exclusions.csv", "derivatives.csv")
