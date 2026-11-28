# Repeat-interaction source admission review

Reviewed on 2026-11-28 for [R1 / #21](https://github.com/qigao/SocioLab/issues/21).
**None of the four candidates below is admitted to the current complete-observation
R1 profile on the evidence inspected.** `NOT_ADMITTED` identifies a gap between a
source and this particular measurement contract; it does not make the dataset
unusable for other research.

**Later follow-up on the same date:** the [released-archive recurrence study](archive-recurrence.md)
subsequently acquired and audited the official Dept3 file after freezing its
protocol. It admits that fixed payload only for prediction of published-record
recurrence. The strict complete-observation decisions below remain unchanged;
the metadata-only descriptions preserve the scope of this earlier review.

The [repeat-interaction specification](repeat-interaction.md) and
[multi-origin evaluator](repeat-interaction-evaluation.md) provide the engineering
path for frozen forecasts and subsequent scoring. Executable evaluation does not
establish source completeness or validate predictive performance. This review
performed source inspection and aggregate structural checks, without fitting or
scoring a real-data model, installing research packages, or executing R.

## Three source conditions

| Condition | Evidence required by the current R1 profile |
| --- | --- |
| Eligible population and presence | A roster and membership intervals independent of future interaction outcomes. The frozen roster must equal the eligible population throughout history and at the origin. Both members of a scored pair must remain present throughout the target. Seeing an actor in an event is insufficient evidence of continuous presence. |
| Observation coverage for the selected action | A declared channel, event definition and coverage intervals that justify interpreting no recorded event as no event of that definition. Coverage must be complete for the relevant history and target exposure; missing, interrupted or unknown observation remains explicit. |
| Closed future follow-up | An independently supported observation endpoint reaching the target boundary, plus the source version and receipt cutoffs used for replay. The last event time, wall clock and end of a downloaded file do not themselves establish `observed_through`. |

The risk set remains ordered pairs with a positive history observation. A source
cannot satisfy these conditions by dropping quiet members, selecting members
using later activity, or declaring every interval complete. A positive event
during incomplete follow-up can remain evidence without becoming a scorable
full-horizon outcome. Historical replay also must not be represented as a
prospectively issued forecast.

## Scope and decisions

| Candidate | What was actually checked | Current decision and decisive gap |
| --- | --- | --- |
| Lintner et al., Mendeley v3 | Public file/folder metadata, four downloaded files with verified hashes, workbook structure, codebook and source paper | `NOT_ADMITTED`: no independent small-group membership/presence, recording boundaries or observation-gap declarations found. |
| McFarland classroom, original `networkDynamic` sources | Seven files at a fixed commit, TSV/SoNIA consistency, constructor, package documentation and original methodological account | `NOT_ADMITTED`: explicit member intervals exist, but complete event coverage for this exact session is not established. |
| SNAP email-Eu-core-temporal Dept3 | Official dataset webpage only; no event file downloaded or audited | `NOT_ADMITTED`: independent membership intervals and closed observation boundaries are not established by the reviewed metadata. |
| SNAP CollegeMsg / Opsahl original source | SNAP and original author's webpages only; neither event file downloaded or audited | `NOT_ADMITTED`: released population is selected by activity; registration records in the original format do not establish full eligibility, coverage or follow-up in the SNAP derivative. |

No raw participant records, identifiers or individual attributes are included in
this repository as part of the review. Counts below describe inspected files or
are explicitly identified as webpage metadata.

## Lintner: video-coded small-group communication

The fixed release is [Mendeley version 3](https://data.mendeley.com/datasets/9c3dth6cwp/3),
DOI [10.17632/9c3dth6cwp.3](https://doi.org/10.17632/9c3dth6cwp.3), published
2024-06-03. Its metadata declares **CC BY 4.0**. The source paper is
[Lintner et al. (2023)](https://doi.org/10.1016/j.dib.2023.109641), also available
as [PMC10579281](https://pmc.ncbi.nlm.nih.gov/articles/PMC10579281/). Version 3
adds off-task coding; the older paper's event count cannot substitute for a
version 3 file audit.

The inspected interaction workbook contains **62 sheets and 5,333 event rows**:
4,723 `on`, 610 `off`, with 601 group-addressed `all` receivers. Its five fields
are `sender`, `receiver`, `type`, `increment`, and `time`; every increment is 1.
No missing time, decreasing time, or duplicate time within a sheet was found.
No nonempty cells outside these columns, workbook defined names, or cell comments
supplied extra membership or observation information.

The codebook defines utterance units and group-directed speech. Although an
utterance has a first and last word, the released rows contain one time field,
not a duration. The paper describes seconds relative to the group's first
utterance. That is not a recording-start or task-start declaration. Observed
first times are 1 or 90 seconds; neither first nor last event time supplies the
missing observation boundaries. An `all` event must remain group-addressed
unless independently documented recipients justify a declared transformation.

The attributes workbook covers 276 students with classroom identifiers, but
does not supply a small-group session roster. The 24 friendship matrices are
classroom survey observations, not attendance records for the video sessions.
The public root file listing and empty folder listing did not reveal another
roster or boundary file. No recording start/stop, absence/return, interruption,
or complete-coding interval declaration was found in the inspected materials.
Consequently, no `coverage.complete` or closed target assertion is warranted.

**Narrower supported use:** replay the released coded events; describe their
directed sequences and on/off-task categories; study associations with separately
measured survey variables under an explicit design. The records alone do not
validate language meaning, motivation, causal influence, or negative events in
unobserved intervals. Release of full transcripts or video was not established.

All four downloaded files matched SHA-256 values in the
[official version 3 file metadata](https://data.mendeley.com/public-api/datasets/9c3dth6cwp/files?folder_id=root&version=3&$start=0&$limit=1000).
Names below use local underscore normalization of the published filenames.

| File | Verified SHA-256 |
| --- | --- |
| `interactional_data.xlsx` | `d8ea8bea2d638aecee2cf0ce29988946e2cba31de0d0b17b1b730abdc6ce4b28` |
| `student_attributes.xlsx` | `c75a240be84c07277f45a92e6b76c7f037149fbd66db5e5520354a0d31d14d0d` |
| `relational_data.xlsx` | `9df3435c113ea62a879ab4588201985da0b08707a8d374d1778cf7c490b5953b` |
| `codebook.pdf` | `48dd12d205aca13043c1536480fdba882486b7d4e2682ef9c508b7228d0a76d5` |

## McFarland: one bounded classroom session

The inspected source is `statnet/networkDynamic` at commit
[`3856a71b47fb31407d630d456bf37119cefac77d`](https://github.com/statnet/networkDynamic/tree/3856a71b47fb31407d630d456bf37119cefac77d).
The original classroom files, constructor and documentation are linked in the
manifest below. Downloaded content also matched each Git tree blob hash.

The vertex TSV contains **20 people**, each with explicit source start 0 and end
49 minutes. The SoNIA file agrees. Two roster members have no outgoing coded
event, so the roster is not merely reconstructed from observed senders. The
constructor reads the supplied vertex spells; these intervals are not default
activity intervals invented by `networkDynamic`.

The edge TSV contains **691 instantaneous rows** (`start_minute == end_minute`):
501 direct rows with weight 1 and 190 broadcast-expanded rows with weight 0.2.
The latter form 10 groups of 19 recipients sharing sender, time and type.
There are 511 distinct event times, from 0.125 to 44 minutes. No self-edge,
exact duplicate row, or event outside the supplied member interval was found.
Time/weight content agrees between TSV and SoNIA representations. The source
interaction categories are `task`, `social` and `sanction`.

These are published coding weights, not communication probabilities. Preserve
the broadcast grouping and simultaneous times; do not treat 190 expanded rows
as 190 separately ordered utterances or reinterpret weight 0.2 as 1/19. The
source supplies relative minutes, without a precise UTC time of day or timezone.

The [original visualization paper, section XI and footnotes 48–49](https://www.cmu.edu/joss/content/articles/volume7/deMollMcFarland/)
supports interpreting node durations as classroom presence/exit and speech events
as instantaneous because utterance duration was unavailable. It describes the
two illustrated sessions as highly accurately coded, while acknowledging that
simultaneous talk can defeat complete observation. High coding accuracy does
not establish an exact-session complete-coverage mask. None was found in the
inspected files. The constructor sets time units but does not read an independent
event-coverage declaration.

The source therefore supports bounded member records and coded interaction
records. **It does not justify complete classroom-communication coverage.** The
last coded event at minute 44 cannot establish either observation closure at 44
or verified silence from 44 to 49. Explicit member presence through 49 does not
resolve that distinction.

**Narrower supported use:** descriptive replay of recorded direct and broadcast
speech, with source-declared presence and retained coding weights/types. An
observation-error study is possible with an appropriate additional measurement
model. This review supplies no empirical qualification for such a model.

The package `DESCRIPTION` declares **GPL-3**. A separate dataset-specific
licence was not found among the seven inspected files. The original paper
invites research reproduction, but this review does not infer a separate
permissive data licence. Raw classroom files are not redistributed here.

### Fixed source manifest

All paths below are within the fixed commit above; hashes identify the inspected
bytes. The edge/vertex files expose columns for endpoints, times and coding
metadata; participant-level values are deliberately omitted from this review.

| Source path | SHA-256 |
| --- | --- |
| [`inst/extdata/cls33_10_16_96_vertices.tsv`](https://github.com/statnet/networkDynamic/blob/3856a71b47fb31407d630d456bf37119cefac77d/inst/extdata/cls33_10_16_96_vertices.tsv) | `d6ced485d75240d2709ac922495fc1c4122fb36c25c438f8c88a99f10c4a8df9` |
| [`inst/extdata/cls33_10_16_96_edges.tsv`](https://github.com/statnet/networkDynamic/blob/3856a71b47fb31407d630d456bf37119cefac77d/inst/extdata/cls33_10_16_96_edges.tsv) | `645759bf1008a65438911d0f61ab620ce28a240db69d8e95d3928c4177cf5278` |
| [`inst/extdata/cls33_10_16_96.son`](https://github.com/statnet/networkDynamic/blob/3856a71b47fb31407d630d456bf37119cefac77d/inst/extdata/cls33_10_16_96.son) | `886e229a7bca21fd9afa85a9132621554ce7dfec291cab0b72084526e17a6d17` |
| [`nonsource/relatedCode/mcfarlandDataFormat.R`](https://github.com/statnet/networkDynamic/blob/3856a71b47fb31407d630d456bf37119cefac77d/nonsource/relatedCode/mcfarlandDataFormat.R) | `bbe29f3031b8e608ad0088182187a3a4638d5618b75e461bac723c9cb673e541` |
| [`man/classrooms.Rd`](https://github.com/statnet/networkDynamic/blob/3856a71b47fb31407d630d456bf37119cefac77d/man/classrooms.Rd) | `8a5cee086c13a79b7bf9d5a95971e3a2877d142351a2b3e013c7c8412453b188` |
| [`DESCRIPTION`](https://github.com/statnet/networkDynamic/blob/3856a71b47fb31407d630d456bf37119cefac77d/DESCRIPTION) | `54bae41457cb213832473d8619ac1fd7fa36c7025bcf6c6a447b1f9ff703c306` |
| [`README.md`](https://github.com/statnet/networkDynamic/blob/3856a71b47fb31407d630d456bf37119cefac77d/README.md) | `3ba7fc6785d76187c9c1f6440457e5641529c7f0e0ab4042b968b587e55cb5cb` |

## SNAP email-Eu-core-temporal Dept3: metadata only

The [official SNAP page](https://snap.stanford.edu/data/email-Eu-core-temporal.html)
reports 89 nodes, 12,216 temporal edges and 802 days for Dept3. It describes
intra-institution email, excluding external correspondence, and expands each
recipient into a directed edge. Times are seconds relative to zero. Its
description of all internal email is useful evidence about the intended log
scope; it does not provide independent member entry/exit intervals, collection
boundary records or interruption declarations in the reviewed metadata.

**Decision:** `NOT_ADMITTED` to the current profile. A defensible narrower target
could be recurrence of a row in a specified released email log. Such a study
must explicitly define its roster, observation universe and endpoint convention,
and must not extend the result to all real communication. No file was downloaded,
so row integrity, a fixed file hash, exact boundary values and reuse terms have
not been verified in this review. The dataset page's counts are not a local
file-audit result.

## CollegeMsg: metadata only, with a population-selection issue

The [SNAP page](https://snap.stanford.edu/data/CollegeMsg.html) describes a parsed
version of university-platform private messages: 1,899 users, 59,835 temporal
edges and 193 days, with Unix-second timestamps. The
[original author's dataset page](https://toreopsahl.com/datasets/) states that
the released population includes users who sent or received at least one message;
it also identifies registration events as self-loops in the original longitudinal
format. This is evidence beyond ordinary event endpoints, but retention of those
registration records in the SNAP derivative was not checked.

**Decision:** `NOT_ADMITTED`. Selecting the full released active population can
use future activity; registration alone does not prove continuous eligibility,
complete observation or a closed follow-up interval. **Narrower use:** a declared
released-message-log recurrence study, after separate source/version and exposure
review. Neither file was downloaded, so no file hash, row-level findings or
data-licence verification is claimed. The whole platform also exceeds the current
200-person profile limit; a future-defined active subset would not resolve the
scientific admission gaps.

## What would enable the next real validation

A candidate can be reconsidered when the source supplies the missing evidence:

1. **An independent eligible roster:** session/group assignment and actual
   presence intervals, including quiet members and departures/returns. Classroom
   membership, survey participation and registration need explicit mappings to
   the selected interaction setting.
2. **Bounded observation:** recording or log-collection start/stop, relevant
   interruptions, coding completeness and the meaning of missing entries for the
   selected action. For McFarland, this specifically requires session-level
   coverage evidence beyond the already documented member intervals.
3. **A source-supported future boundary:** follow-up closure for every planned
   target, independent of the last event, with source revision and late-arrival
   handling. Archived reconstruction must be labelled retrospective.
4. **A declared event transformation:** distinguish direct speech, group address
   and per-recipient expansion; retain simultaneous events and measured time
   resolution. Do not create addressees, speech durations or lexical content.
5. **A frozen study and reproducible source:** verified use/redistribution terms,
   fixed file/version hashes, a past-only roster and risk set, predeclared origin
   schedule and horizons, and the existing coverage-aware scoring/evaluation
   contract. Report exclusions and dependence across dyads and origins.

If a source supports only the released-log target, that narrower measurement
contract needs an explicit separate review. It must not be made to pass the
current complete-observation profile by manufacturing membership or coverage
declarations. Running additional origins cannot repair missing source evidence,
and a successful engineering replay cannot establish motives, relationship
termination or causal effects.
