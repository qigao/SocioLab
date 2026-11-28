# Observation evidence for the released email archives

This review follows the already executed [Dept3 recurrence study](archive-recurrence.md)
and [Dept2 network comparison](network-recurrence.md). Their empty archive
windows prompted a review of the original source descriptions. This is a
**post-result source review**; it is not a new prediction experiment or a
pre-acquisition registration. No additional department file was acquired, no
raw records or new outcomes were examined, and no authors were contacted.

The decision remains **NOT_ADMITTED for strict R1 complete-observation
scoring**. The reviewed sources support a narrower released-record target.
Real observation coverage is **unknown for every evaluated window**, including
windows containing records. The presence of some records does not establish
complete capture of all eligible interactions throughout an interval.

The machine-readable evidence is
[`source-review.json`](experiments/2026-11-28-archive-observation/source-review.json).
It distinguishes publisher statements, unresolved provenance and the study's
admission decision. These conclusions describe the materials inspected here;
the search is not claimed to exhaust every possible source or explanation.

## What the publisher states

The [official temporal dataset page](https://snap.stanford.edu/data/email-Eu-core-temporal.html)
describes the data as internal institutional email and broadly claims capture
of all incoming and outgoing email between members. It excludes communication
with the outside world. Each recipient contributes a directed row, and four
departmental subnetworks are provided. The time field is expressed as seconds
starting at zero. The listed span is 803 days for the full temporal network and
Dept2, and 802 days for Dept3.

That broad source claim is retained as evidence. The page does not supply
interval-specific capture declarations, observation interruptions, participant
entry/exit histories or an absolute date for source zero. The review therefore
does not convert the claim into verified coverage or membership for each
forecast window.

The [static core page](https://snap.stanford.edu/data/email-Eu-core.html)
describes one department label per person among 42 departments and links the
core's provenance to the larger email-EuAll collection. Static labels do not
provide time-varying department eligibility. The temporal and static pages
also warn that identifiers differ between releases; equality of identifiers
cannot be used as a cross-release person mapping.

## Original-paper evidence and an unresolved time discrepancy

The 2017 paper,
[Paranjape, Benson and Leskovec, *Motifs in Temporal Networks*](https://cs.stanford.edu/~jure/pubs/motifs-wsdm17.pdf),
provides the following relevant evidence:

- **Table 1 and section 5.1:** EMAIL-EU has 986 nodes, about 332,000 temporal
  edges and an 803-day span; the studied event data have one-second resolution.
- **Section 5.2:** four institutional departments were extracted as subnetworks
  for motif comparisons.
- **Section 3:** unique times simplify the theoretical presentation, and the
  methods can be adapted to tied timestamps. This does not provide a specific
  tie-breaking policy for the released email rows.
- **Reference 17:** the source chain points to the 2007 graph-evolution paper.

Neither the inspected dataset discussion nor those methodological sections
explain the observed internal empty periods or give a departmental clock
mapping and observation mask.

The [official email-EuAll page](https://snap.stanford.edu/data/email-EuAll.html)
describes an older collection from October 2003 to May 2005, termed 18 months,
with 3,038,531 emails. It limits its complete-graph claim to 1,258 institutional
addresses. This is related collection context, not an exact coverage contract
for the current departmental files.

[Leskovec, Kleinberg and Faloutsos, *Graph Evolution: Densification and Shrinking Diameters*](https://www.cs.cmu.edu/~jure/pubs/powergrowth-tkdd.pdf),
section 3.1.5, confirms the older date range and institutional-core scope.
Its analyzed graph connects addresses after reciprocal exchange, and it also
discusses two-month sliding-window graphs. These graph definitions differ from
the current temporal archive's directed recipient records. The paper's account
of a largely stable institutional core is not an individual presence history
for the later department exports.

Thus the reviewed provenance contains **803-day temporal-release metadata**
and **an older 18-month collection description**. No inspected transformation
note reconciles the two. This is recorded as an unresolved discrepancy, not as
proof that a particular source is wrong. It does not authorize assigning an
October 2003 calendar origin, truncating the released times, or labeling later
rows as erroneous.

## What remains unknown

| Question | Current evidence status |
| --- | --- |
| Whether a fixed released payload contains rows in an interval | Computable from that payload |
| Whether an empty interval is bracketed by earlier and later archive rows | Computable from source-relative timestamps |
| Capture completeness during any particular interval | UNKNOWN |
| Institutional or departmental eligibility throughout an interval | UNKNOWN |
| Absolute date and timezone of source zero | UNESTABLISHED |
| Shared calendar alignment of Dept2 and Dept3 source times | UNESTABLISHED |
| Whether an empty interval reflects inactivity, collection interruption or export processing | UNKNOWN |
| Whether a real relationship ended | NOT_IDENTIFIED |

The reviewed primary pages and papers contain no located explanation of the
already observed internal gaps. The review does not establish a real outage,
prove sustained inactivity, or exclude explanations outside the inspected
materials. Matching numbered relative windows in two files does not establish
that the files share a calendar zero or experienced simultaneous events.

These uncertainties apply to nonempty intervals too. A nonempty window proves
that the release contains records under its own measurement definition. It
does not provide the missing observation, eligibility or follow-up evidence
needed to interpret every absent pair as a verified real-world negative.

## Consequences for the observation audit

The audit should keep distinct fields for archive row presence, real capture
coverage, temporal membership, calendar mapping and gap cause. Descriptive
record-free intervals can be measured without assigning them an explanation.
Their boundaries should identify the preceding and following recorded source
times, and their endpoint convention should be explicit.

No event count, maximum inter-record gap, resumed activity, source file extent
or fitted probability establishes complete observation on its own. An empty
interval remains usable as a negative under the existing **fixed archive**
target. It remains unqualified for the stricter **complete real observation**
target. These separate contracts preserve the original experiments instead of
relabeling their outcomes after seeing the results.

A later coverage declaration would need evidence that identifies its source
version, event scope, participant mapping, eligible interval and capture
assumptions. The current review creates no such declaration. It also does not
infer missingness mechanisms, estimate a correction factor or fit a new model.

## Release identity and licensing scope

The [temporal-motifs data page](https://snap.stanford.edu/temporal-motifs/data.html)
links the temporal email release and repeats its size and 803-day span. No
official coverage supplement, temporal-export mapping or release-change
explanation was located in the inspected source chain and targeted searches.
Existing download fingerprints bind the exact files used by SocioLab; they
do not authenticate the collection process. HTTP modification metadata also
does not establish historical recording coverage.

The linked [SNAP license](https://snap.stanford.edu/snap/license.html) concerns
software source and binary redistribution. No dataset-specific redistribution
grant for these exact email payloads was stated on the inspected primary pages.
The software BSD terms are not transferred to the raw dataset. This review
adds attributed metadata and methodological analysis without redistributing
participant rows or private pair forecasts.

## Reviewed primary sources

| Evidence ID | Primary source and location |
| --- | --- |
| `snap_temporal` | [Temporal release page](https://snap.stanford.edu/data/email-Eu-core-temporal.html): Dataset information, statistics, files and data format |
| `snap_core` | [Static core page](https://snap.stanford.edu/data/email-Eu-core.html): Dataset information and community-membership format |
| `snap_euall` | [Larger email collection page](https://snap.stanford.edu/data/email-EuAll.html): Dataset information |
| `wsdm_2017` | [Motifs paper](https://cs.stanford.edu/~jure/pubs/motifs-wsdm17.pdf): section 3, Table 1, sections 5.1/5.2 and reference 17 |
| `tkdd_2007` | [Graph-evolution paper](https://www.cs.cmu.edu/~jure/pubs/powergrowth-tkdd.pdf): section 3.1.5 |
| `snap_motifs_data` | [Temporal-motifs data page](https://snap.stanford.edu/temporal-motifs/data.html): dataset table |
| `snap_software_license` | [SNAP license](https://snap.stanford.edu/snap/license.html): source/binary license text |
