# Source admission for forecasts at multiple origins

This **2026-11-28 documentation review** starts from commit
`c6d82a6574d51abb7648aab859ee60fde140ac02` (PR #14). It covers the sources
already discussed in this repository and the datasets directly listed in the
[Oxford/SIENA official directory](https://www.stats.ox.ac.uk/~snijders/siena/siena_datasets.htm),
with their linked documentation. It is not a survey of all public datasets.
The [machine-readable review](experiments/2026-11-28-forecast-evaluation/source-admission.json)
records the same boundary.

**No new source is admitted by this review.** Knecht's four-wave classroom
excerpt is a concrete candidate, with status **`NOT_ADMITTED` to the current
complete-observation, fixed-roster forecast profile**. This is an interface
and evidence decision; it does not declare the study unusable for every
analysis. No individual-level archive was downloaded or inspected in this
review, and no forecast, fit or parameter search was run.

## Knecht: distinguish documented measurements from inspected data

The [official tutorial description](https://www.stats.ox.ac.uk/~snijders/siena/tutorial2010_data.htm)
documents a Dutch class of 26 pupils, measured four times from September 2003
to June 2004, at approximately three-month intervals.

| Documented component | Official file reference and interpretation |
| --- | --- |
| Friendship | `klas12b-net-1.dat` through `klas12b-net-4.dat`; directed nominations of up to 12 classmates |
| Network codes | `0` = no nomination, `1` = nomination, `9` = missing, `10` = not a classroom member (structural zero) |
| Four-wave behavior | `klas12b-delinquency.dat`; rounded average of four items: stealing, vandalism, graffiti and fighting; scale 1–5; `0` = missing |
| Three-wave behavior | `klas12b-alcohol.dat`; only waves **2, 3 and 4**; drinking with friends during the preceding three months; scale 1–5; `0` = missing |
| Composition | `klas12b-present.dat`; the documented `klas12b.r` example places one pupil's departure immediately after wave 2 |

The tutorial's five frequency categories run from never to more than ten
times. The supplied delinquency outcome is a rounded composite of category
codes. A loss on that composite cannot be interpreted as a count of offences.

The class size and departure above are **published documentation facts**.
Actual archive row counts, row alignment, missing-cell counts, nonmember-cell
counts and behavior missingness have **not** been checked. Unknown counts
remain `null` in the review record; they do not mean zero. The documentation
does not establish historical receipt or correction times for a prediction
issued at a particular cutoff. Archive identity and applicable usage terms
also remain unverified in this review.

### The full-study codebook is a separate source profile

The [official ICS Codebook 61](https://www.stats.ox.ac.uk/~snijders/siena/CodebookNetworksAndActorAttributesInEarlyAdolescence.pdf)
describes `pupilswaveV.sav`, `pupilswaveW.sav`, `pupilswaveX.sav` and
`pupilswaveY.sav`, with interview date, school/class identifier and pupil-number
fields. Its original friendship fields `friend1-12` use missing codes
`98/99`. Its behavior items `actsteal`, `actbreak`, `actfight` and `actsmear`
use missing codes `0/9`. These are not the tutorial matrices' encodings.

The codebook lists `actalcoh` at V/W/X/Y. That does **not** supply a first-wave
column for the tutorial's three-column alcohol file, establish equivalence
between the two variable extractions, or authorize a reconstruction. The
codebook's requested acknowledgments are not a verified license for every
distributed artifact.

The directory links the full study through
[DOI 10.17026/dans-z9b-h2bp](https://doi.org/10.17026/dans-z9b-h2bp).
The [current official DANS landing page](https://ssh.datastations.nl/dataset.xhtml?persistentId=doi:10.17026/dans-z9b-h2bp)
returned an anti-bot page during this review. The current full archive,
access conditions and license were not verified. This access observation does
not establish that the underlying dataset is unavailable.

### Why the candidate remains `NOT_ADMITTED`

The [current forecast contract](behavior-forecast.md#input-boundaries-and-time)
requires complete declared networks and behavior for the same supplied actors.
Knecht documents changing classroom membership and encodings for unobserved
values. The present review neither audits those values nor defines an
admitted membership and missingness policy for forecasting.

An adapter must preserve the distinction between observed non-nomination,
unknown nomination and ineligible classroom dyads. Setting `9` to zero, or
turning a departed pupil into an ordinary in-class isolate, would erase that
distinction. Selecting only pupils who later remain enrolled or answer every
future survey would condition the roster on future information. It cannot be
used to manufacture an otherwise complete fixed panel. The source audit must
precede any decision about prediction eligibility, abstention or evaluation
coverage.

## Other candidates in the reviewed official directory

These are documentation findings, not new audits of the downloadable files.
The review found no additional directly listed source that could immediately
enter the current complete, fixed-roster profile with at least four aligned
network and behavior waves.

| Official source | Documented limitation for this task |
| --- | --- |
| [s50](https://www.stats.ox.ac.uk/~snijders/siena/s50_data.htm) | Three network/behavior waves; the 50-person excerpt is restricted to numerical illustration because its population is not properly delineated |
| [Full Glasgow study](https://www.stats.ox.ac.uk/~snijders/siena/Glasgow_data.htm) | Three measurement waves; it does not add a fourth wave to s50 |
| [van de Bunt](https://www.stats.ox.ac.uk/~snijders/siena/vdBunt_data.htm) | Seven network waves, but only `vars.dat` is described for the attributes; no four-wave behavior series is documented. The 32-person excerpt was selected from 49 using subsequent dropout and response history |
| [Zeggelink](https://www.stats.ox.ac.uk/~snijders/siena/Zeggelink_data.htm) | Seven planned network occasions, five supplied occasions; actor attributes in `stud98.txt` were collected at `t0` |
| [van Duijn](https://www.stats.ox.ac.uk/~snijders/siena/vDuijn_data.htm) | Five network occasions, but `cov1.dat` and `cov4.dat` supply attributes at only two occasions; unequal intervals and later nonresponse also require treatment |
| [Baerveldt](https://www.stats.ox.ac.uk/~snijders/siena/BaerveldtData.html) | Two network/behavior waves |
| [EIES](https://www.stats.ox.ac.uk/~snijders/siena/EIES_data.htm) | Two relationship networks; the attributes and message-count matrix do not provide four aligned behavior waves |
| [Kapferer](https://www.stats.ox.ac.uk/~snijders/siena/kapfdata.htm) | Four matrices represent two relationship types at two times, rather than four time points |
| [Lazega](https://www.stats.ox.ac.uk/~snijders/siena/Lazega_lawyers_data.htm) | The description supplies several relationship layers and attributes, without establishing four repeated waves of the same behavior |
| [Harry Potter](https://www.stats.ox.ac.uk/~snijders/siena/HarryPotterData.html) | Coded relationships among fictional characters; no eligible repeated real-person behavior target is documented |

The repository's [Mauldin source review](mauldin-source-admission.md) also
remains separate: its belonging and multicultural-perspective measurements
occur at waves 1, 3 and 4, while its first-wave relationship is know-of and
wave 2 has no such behavior measurements. The
[Hypertext source review](recorded-contact-case.md) supplies contact records,
without an independent attendance or device-uptime ledger. A zero-contact
window cannot supply an observed absence or nonparticipation label.

## How many forecast origins are possible?

The following is a **design inference**, not an empirical source finding or
an executed evaluation. Assume aligned consecutive waves, admissible
observations and at least one completed training transition. Use one-based
source-wave numbers in this section.

The current origin-wave feature profile needs two known waves: wave 1 supplies
training features and wave 2 supplies their label. It can then issue a forecast
from wave 2 for wave 3. Thus **s50 supports only one legal origin** for this
profile. Treating wave 2 as an additional held-out target would remove the
transition needed to fit its OLS baselines.

| Aligned waves | Potential origins for current origin-wave features | Potential origins if a future extension uses two-wave network changes |
| ---: | ---: | ---: |
| 3 | 1 | 0 |
| 4 | 2 | 1 |
| 5 | 3 | 2 |

For the proposed extension, every network-change feature must be calculated
from **two already observed networks**. Training an origin at wave 2 then
needs networks 1/2 and behavior at wave 3. The first held-out forecast is issued
at wave 3 for wave 4; the second is issued at wave 4 for wave 5. Accordingly,
**two origins with trained network-change features require at least five
waves** under these assumptions. The existing predictor does not implement
that extension, and a future network is never an admissible feature.

Four eligible waves would permit the present profile's planned sequence:
train on `1 -> 2`, save the wave-3 forecast, reveal and score wave 3, then use
only the now-known waves 1–3 to save a wave-4 forecast before revealing wave 4.
Splits, features and losses must be fixed before the evaluation sequence;
results must retain every declared origin, including failures. Origin count
alone does not establish stable prediction, independent replications or a
causal network effect.
