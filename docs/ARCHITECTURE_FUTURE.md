# Future architecture direction

FlipFinder v1 intentionally keeps an iPhone-focused model. It should not be refactored during v1 maintenance merely to anticipate future categories.

## iPhone-specific v1 seams

- `DeviceInfo`: battery health, iCloud/operator locks, SIM, and package fields.
- OLX parameter normalization and iPhone model extraction.
- iPhone condition and battery scoring signals.
- Market benchmark keys tied to phone model and storage.

## V2 abstractions

| V1 concern | Future abstraction |
| --- | --- |
| OLX/browser integration | `MarketplaceAdapter` |
| iPhone model/storage identity | `ProductIdentity` |
| Device-specific fields | `CategoryAttributes` |
| Current iPhone profile | `ProductProfile` |
| Benchmark grouping | `GenericBenchmarkEngine` |

`ProductProfile` should define canonical identity, extractors, comparable attributes, deterministic adjustments, and validation constraints. Marketplace adapters should collect and normalize source data without knowing a category’s scoring rules. This permits multiple active profiles and multi-category benchmarks while preserving v1 behavior.
