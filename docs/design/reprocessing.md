# Reprocessed-value pricing

An option to price ore and ice from what it reprocesses into, rather than from
the ore's own market price.

## Purpose

A buyback that takes ore does not resell the ore — it reprocesses it and sells
the minerals. Pricing ore at its market price therefore prices the wrong thing.
Ice makes this sharpest: 10 000 Clear Icicle is worth roughly 2.9 billion ISK in
isotopes and heavy water, and the operator's payout should follow that number.

This adds a second **valuation basis**. An item matched by a reprocessing rule is
valued from the sum of its reprocessing outputs, each priced at market and each
discounted by its own existing percentage rule. The item's own market price is
never consulted.

Percentages are unchanged. Reprocessing decides *what* is being valued;
`pricing/domain/resolution.py` still decides *what fraction of it* is paid, and
its four absolute tiers are untouched.

## Verified facts this depends on

Verified against the EVERef reference-data archive the catalogue seeder already
downloads, and against `https://janice.e-351.com/api/rest/v2/swagger.json`.

### Janice cannot do this for us

The appraisal endpoint takes `market`, `designation`, `pricing`,
`pricingVariant`, `comment`, `persist`, `compactize` and `pricePercentage`. There
is no reprocessing parameter, and no yield or material data anywhere in the
response. Searching the whole spec for "reprocess", "refin", "mineral", "compress"
and "yield" returns nothing; the only hits for "material" and "ore" are
`researchingmaterialefficiency` and the word "stored".

Janice's website offers reprocessing views. Its REST API does not.

### The yields are in types.json, not type_materials.json

`type_materials.json` ships in the archive but is **empty — three bytes, `{ }`**.
The data moved into `types.json`, which the seeder already streams:

```
1230 Veldspar
  is_ore         : True
  portion_size   : 100
  category_id    : 25
  type_materials : {"34": {"material_type_id": 34, "quantity": 400}}
```

Each type also carries `is_ore` and `ore_variations`. Neither is used by this
design — selection is by explicit rule targets rather than inferred — but both are
noted because they are the obvious basis for a future "all ore" or "all Veldspar
variants" target.

Volumes: 9 541 types carry reprocessing data across the whole archive, giving
47 051 material rows. Only published types in known groups are imported, which is
8 077 types and 41 017 rows, one of which points at an unpublished material — so
**41 016 rows are importable**, and that is the number a successful seed reports.
462 of the types and 1 142 of the rows are in the Asteroid category.

### Ice is a group, and it never leaves a remainder

Ice is **group 465 inside category 25 (Asteroid)** — not its own category. It is
therefore a Group-level target, and the existing Type > Group > Category
specificity makes "Asteroid reprocesses at one rate, Ice at another" work without
new precedence rules.

`portion_size` decides how much of a stack can be reprocessed at all:

| group | portion_size |
|---|---|
| Ice (465), all 26 published types | 1 |
| Raw ore (Veldspar, Scordite, …) | 100 |
| Compressed ore variants | 1 |
| Fluorite (2024) | 1000 |
| AIR Ore Asteroid Resources (4161) | 333 |

So **ice never has an unreprocessable remainder** — every unit reprocesses alone.
Raw ore does: 10 050 Veldspar is 100 batches plus 50 leftover units.

### The outputs are all Material category items

Minerals sit in group 18 (Mineral), ice products in group 423 (Ice Product), both
under **category 4 (Material)**. Every existing rule level therefore already
reaches them — a Material category default, a Mineral group rule, or a Tritanium
type rule all work with no new machinery.

### The pricer endpoint resolves nothing server-side

`POST /api/rest/v2/pricer` takes a **`text/plain` body, one type id or name per
line** — the same raw-body style as the appraisal endpoint — and returns
`PricerItem[]`.

`PricerItem` exposes `immediatePrices` and `top5AveragePrices` but **no
`effectivePrices`**. The appraisal endpoint applies the configured
`pricing`/`pricingVariant` server-side and hands back `effectivePrices`; the
pricer does not. The adapter must therefore select the variant and the basis
itself, or mineral prices will silently ignore the operator's configuration while
ore prices honour it.

## The valuation model

For one item matched by a reprocessing rule:

```
batches   = quantity // portion_size
remainder = quantity %  portion_size          → shown, not paid

for each output material of the type:
    units   = floor(yield_per_batch × batches × rule.yield_rate)
    percent = resolve_price(material, ruleset, now)     ← existing tiers
    value   = units × market_price × percent / 100

line_total = Σ value
```

### Rounding is applied to the whole lot, once

The `quantity` in `type_materials` is what **one batch** of `portion_size` yields.
The floor must be applied after multiplying by every batch, not to each batch:

    floor(quantity × batches × rate)        correct
    floor(quantity × rate) × batches        wrong

EVE reprocesses the selected stack in one operation, and the difference is not
academic. For 10 000 Clear Icicle at 0.9063 — where `portion_size` is 1, so
batches equal units:

| output | rounded per batch | rounded once |
|---|---|---|
| Heavy Water | 620 000 | 625 347 |
| Liquid Ozone | 310 000 | 317 205 |
| Helium Isotopes | 3 750 000 | 3 752 082 |
| Strontium Clathrates | **0** | 9 063 |

Rounding per batch **zeroes any material yielding 1 per batch** — `floor(1 ×
0.9063) == 0` — destroying Strontium Clathrates outright. Total shortfall
41 086 761 ISK, or 1.41%.

### Worked example

10 000 Clear Icicle, yield 0.9063, Ice Product group at 80% with Helium Isotopes
overridden to 90% at type level:

| output | units | unit price | % | value |
|---|---|---|---|---|
| Heavy Water | 625 347 | 99.40 | 80 | 49 727 593.44 |
| Liquid Ozone | 317 205 | 85.99 | 80 | 21 821 166.36 |
| Helium Isotopes | 3 752 082 | 742 | 90 | 2 505 640 359.60 |
| Strontium Clathrates | 9 063 | 4 236 | 80 | 30 712 694.40 |
| **line total** | | | | **2 607 901 813.80** |

Gross before percentages: 2 911 871 661.75 ISK.

### Materials with no rule are shown, not paid

An output whose `resolve_price` yields no configured rule contributes nothing, and
the rest of the line is still paid. It is recorded with `is_unpriced=True` so it
appears in the breakdown on the quote page and in the admin.

The alternative — flagging the whole line — was considered and rejected. This
choice keeps quotes flowing, and the visible breakdown is what stops a forgotten
mineral rule from becoming an invisible underpayment.

A blacklisted material resolves to 0% through the normal tiers and contributes
zero, which needs no special handling.

## Selection: a reprocessing rule that carries its own yield

```python
class TargetedRule(models.Model):      # abstract: label + categories/groups/types
class CustomRule(TargetedRule):        percent
class SaleRule(TargetedRule):          percent, valid_from, valid_to
class ReprocessingRule(TargetedRule):  yield_rate      # Decimal(6, 4)
```

Moving `percent` out of the abstract base and into the two concrete classes is a
**no-op at the database level**: abstract base fields are already emitted onto
each child's own table, so no column moves.

The yield lives on the rule, not in Site configuration, because EVE has separate
reprocessing skills for ore and for ice. A single global rate would be wrong for
one of them. Two rules express it directly:

| rule | target | yield |
|---|---|---|
| Ice reprocessing | group Ice (465) | 0.9063 |
| Ore reprocessing | category Asteroid (25) | 0.8734 |

Specificity resolves these without new precedence: Ice matches at Group level and
beats the Asteroid Category match, exactly as a Group percentage rule beats a
Category one today.

`find_conflicts` needs `getattr(instance, "percent", 0)` so the existing overlap
validation works for a rule that has no percent.

`PriceSourceKind` gains `REPROCESSED`.

### Reusing the specificity walk without contorting `Rule`

The domain needs a second rule shape carrying `yield_rate` instead of `percent`.
Overloading `Rule.percent` to hold `0.9063` would be a trap — every other reader
of that field means percentage points, where 0.9063 would be nine tenths of one
percent.

Two small changes let `_best_match` serve both unchanged:

```python
# pricing/domain/ruleset.py
def match_level(item, *, category_ids, group_ids, type_ids) -> MatchLevel | None:
    """Shared by Rule and ReprocessingRule."""

@dataclass(frozen=True)
class ReprocessingRule:
    label: str
    yield_rate: Decimal
    category_ids / group_ids / type_ids
    def match_level(self, item): ...      # delegates to the function above
    @property
    def tie_break_value(self): return self.yield_rate

# Rule gains the same property, returning self.percent
```

`_best_match` then compares `rule.tie_break_value` rather than `rule.percent`,
and its same-level tie-break — highest wins, as a defensive backstop against
direct ORM writes — keeps working for both. `RuleSet` gains
`reprocessing_rules: tuple[ReprocessingRule, ...]`, loaded by `load_ruleset`.

Rejected alternative: a "price by reprocessing" checkbox on Category defaults plus
one global yield setting. Fewer concepts, but category-only — it cannot treat Ice
differently from the rest of Asteroid, which is the requirement.

## Data model

### catalog

```python
EveType.portion_size = PositiveIntegerField(default=1)

class EveTypeMaterial(models.Model):
    type     = ForeignKey(EveType, related_name="materials")
    material = ForeignKey(EveType, related_name="reprocesses_from")
    quantity = PositiveIntegerField()
```

Both are populated on the pass the seeder already makes over `types.json`, so
seeding costs no extra download.

All 47 051 rows are imported, not only the Asteroid ones. It is a trivial table
size, and it makes reprocess-pricing modules or ships later a configuration
change rather than a re-seed.

**Rows whose type or material is not in the catalogue must be skipped and
counted, never inserted.** 9 541 types carry reprocessing data while 26 992 types
are published, so unresolvable references exist. This is the same foreign-key
breakage that the original seeder hit when filtering on `published`.

### buyback

```python
class QuoteItemMaterial(models.Model):
    quote_item      = ForeignKey(QuoteItem, related_name="materials")
    type_id, type_name
    quantity                       # units recovered after yield and rounding
    unit_price, percent_applied, line_total
    is_unpriced     = BooleanField # no rule: displayed, contributes nothing
```

`QuoteItem` additionally freezes `yield_rate_applied` and `portion_size_applied`.
Without them, editing a reprocessing rule would change what an existing quote
claims it was priced at, and the quote page promises the opposite: "This page is
permanent and will not change."

## Flow

`generate_quote` gains one step, and only when a reprocessing rule matches:

1. Janice appraisal, as today — market prices for the pasted items.
2. Load the ruleset, now including reprocessing rules.
3. Classify the items; find which match a reprocessing rule.
4. For those, read `EveTypeMaterial` and collect every distinct output type id.
5. **One** `price_types` call for all of them.
6. Classify the materials and `resolve_price` each.
7. Build lines: a reprocessed line carries its `QuoteItemMaterial` children.

`price_types(type_ids) -> dict[int, Decimal]` joins the existing
`PriceAppraisalGateway` port — the same upstream service, a second operation.

The call goes **outside** the atomic block, like the appraisal call. Holding a
transaction open across a 30-second HTTP request is the mistake already fixed in
`generate_quote`.

No caching. One extra call per quote containing ore is acceptable, and a cache
would need invalidation rules that nothing yet justifies.

## Failure modes

| Condition | Behaviour |
|---|---|
| type has no reprocessing data | reprocessing rule cannot apply; falls through to normal market pricing |
| `quantity < portion_size` | zero batches, whole line is remainder, line total 0 and flagged |
| output material has no rule | contributes nothing, recorded `is_unpriced`, rest of line paid |
| output material blacklisted | 0% through the normal tiers, contributes nothing |
| `price_types` fails or times out | `AppraisalError`, surfaced as the existing friendly error page — no partial quote |
| pricer returns no row for a type | treated as unpriced rather than assumed free |
| `yield_rate` of 0 | every output rounds to 0; the line is flagged rather than quoted at 0 silently |

## Testing

The valuation is a pure function over frozen value objects, so the truth table
needs no database and no network:

- `portion_size` 1, 100 and 1000: batches and remainder
- whole-lot rounding, and specifically **a material yielding 1 per unit
  surviving** — the Strontium Clathrates regression, worth 1.41%
- per-material percentages, including a type-level override beating a group one
- an unpriced material recorded and excluded from the total
- a blacklisted material contributing zero
- `quantity < portion_size` producing a flagged zero line

Integration:

- the seeder importing `portion_size` and materials, and **skipping rows whose
  material type is absent** rather than raising
- the pricer adapter: `text/plain` body, one id per line, and selecting
  `immediatePrices` vs `top5AveragePrices` and the basis field from `SiteConfig`
- prices as `Decimal` throughout, never `float`
- **editing a reprocessing rule's yield does not alter an existing quote** —
  generate, edit, re-read, assert unchanged

## Deliberate limitations

- **Ore market price is never compared.** A matched item is always valued from
  reprocessing, even when the ore itself trades higher — which happens for
  compressed ore. Changing this would mean two valuations per line and a quote
  page that explains which won.
- **The remainder is not paid for.** It is shown in the breakdown. Paying it would
  require the ore to carry its own percentage rule, reintroducing the basis the
  design removes. Ice never has a remainder.
- **No reprocessing tax.** EVE charges a station tax on reprocessing output; it is
  not modelled. Fold it into the yield rate or the material percentages.
- **Ore variations are not used.** `ore_variations` groups the variant families,
  which would allow "all Veldspar variants" as one target. Types and groups cover
  the need today.

## Operational note

Reprocessing yields arrive with `seed_catalog`. A deployment that seeded before
this feature has `portion_size` defaulted to 1 and no `EveTypeMaterial` rows, so
every reprocessing rule would flag its lines as having no outputs. Re-run
`manage.py seed_catalog` after upgrading; it is idempotent.
