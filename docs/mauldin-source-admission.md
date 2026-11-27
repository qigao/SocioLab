# Mauldin source audit and empirical admission

SocioLab can inspect a caller-supplied copy of the official **Peer Relationships among Master of Social Work Students: Social Network Data** archive and produce an aggregate source audit. The result is **`NOT_ESTIMABLE`**, with `empirical_admitted=false`. Obtaining the source and checking its records does not establish a complete network, a qualified population boundary, or admission to the current SAOM adapters.

This release implements the source-audit stage of [Issue #3](https://github.com/qigao/SocioLab/issues/3). It preserves missingness and source discrepancies instead of changing `sociolab.longitudinal.v1`. It performs no Mauldin fit, row-level dataset export, automatic cleaning, or reconstruction of individual activities.

## Run the offline audit

After installing the base package, supply the ZIP downloaded from the [official MavMatrix catalogue](https://mavmatrix.uta.edu/socialnetworksforsocialgood_datasets/2/):

```bash
python -m pip install -e .
python -m sociolab source mauldin inspect /absolute/path/to/UTA_Social_Networks_Social_Good.zip > mauldin-source-audit.json
```

The CLI reads local source bytes; it does not download the archive. The official download **was successfully obtained for the recorded 2026-11-27 audit**. Those are separate facts: the source is available, and the command remains an offline reader. The raw archive is not vendored in this repository.

A valid audit exits **0** even though its scientific admission status is `NOT_ESTIMABLE`. Malformed input fails with exit code **2**. Unlike the fitting commands, an audit's exit status describes successful inspection, not numerical convergence or empirical admission.

The Python interface is:

```python
from sociolab.mauldin import mauldin_source_report

report = mauldin_source_report("/absolute/path/to/UTA_Social_Networks_Social_Good.zip")
print(report["kind"])                 # MAULDIN_SOURCE_AUDIT
print(report["status"])               # NOT_ESTIMABLE
print(report["empirical_admitted"])   # False
```

The report includes archive/member fingerprints, reviewed-document status, aggregate roster and response counts, per-file coverage and anomalies, recorded nomination turnover, and admission blockers. It does not emit actor IDs, personal attributes, raw nomination rows or free text. The optional cusna runtime is not needed for this audit.

## Source identity and documentation

The [catalogue](https://mavmatrix.uta.edu/socialnetworksforsocialgood_datasets/2/) identifies the dataset through [DOI 10.32855/dataset.2024.05.013](https://doi.org/10.32855/dataset.2024.05.013), with publication date 2021-02-24 and deposit date 2024-03-06. Its recommended citation uses Mauldin (2021). The packaged README instead recommends a four-author 2020 citation. These are retained as source metadata, without silently selecting one year as a new version identifier.

The reviewed [official ZIP download](https://mavmatrix.uta.edu/context/socialnetworksforsocialgood_datasets/article/1000/type/native/viewcontent) has:

| Evidence | Recorded value |
| --- | --- |
| Retrieved | 2026-11-27, from the official MavMatrix download |
| Archive size | 853,589 bytes |
| Archive SHA-256 | `d64a69e38401f2d1b81ae00f57dca670352a443c3a6332ddab4d01ff341d1c01` |
| Packaged `README.txt` SHA-256 | `692c2ba8a7d90375bcc2dd236e069b85191a13ae8c3ff84aa1b9c77a9095b6d7` |
| Packaged `Data Dictionary.pdf` SHA-256 | `0e80647d08871b9bcfff0fb342d6da528c77625f1e9bdac3ef1b21b9ec1ae36e` |

Hash equality identifies the reviewed bytes. It does not authenticate each survey assertion or qualify an analysis. The report distinguishes the supplied archive fingerprint from the reviewed reference fingerprint and records whether the documentation matches the reviewed profile.

### License and population discrepancies remain visible

The catalogue labels the dataset **CC BY 4.0**. The packaged README's sharing/access section instead states **CC BY-NC-ND 4.0**. The audit reports both; it does not resolve their legal precedence or grant permission to redistribute a transformed dataset. This release publishes software and aggregate audit evidence, without copying the raw data into the repository.

The catalogue describes a class with `N=142`. The README sample section mentions 148 incoming students, then uses 145 as the denominator for 142 study enrollees. `ParticipationAcrossWaves.csv` actually contains **145 distinct roster records**. These numbers have different stated roles and an unresolved discrepancy; 145 roster entries are not proof of 145 observed respondents or a complete population boundary.

Roster scope also needs clarification. The README methods describe a program-wide roster including people not enrolled in the study. The dictionary's network questions refer to classmates in the respondent's cohort. This prevents treating every unlisted pair among all 145 records as a verified negative tie solely from an edge-list absence.

The related [2022 paper, DOI 10.3390/educsci12030205](https://www.mdpi.com/2227-7102/12/3/205), describes a narrower analysis: §2.2 starts with 74 full-time regular-track students, 72 study enrollees, and 70 remaining participants. Section 2.6 specifies a full-time 2014–2016 roster with separate no-ties and nonresponse choices. Sections 2.5/2.7 distinguish seven survey nonrespondents from nine actors with missing friendship reports. That 70-person analysis and its ERGM results do not independently qualify the full 145-row archive for SocioLab's joint SAOM. A reproducible cohort selection and its boundary assumptions would be a separate analysis specification.

## Keep waves, relationships and measurements distinct

The packaged README methods and dictionary pp. 22–23 describe these observations:

| Wave | Collection period | Available relationship observations | Relevant measurement limits |
| --- | --- | --- | --- |
| 1 | July/August 2014 orientation | Free-recall knowledge of incoming students | This is not a friendship wave |
| 2 | October 2014, eight weeks into the first semester | Roster-based academic discussion, friendship and professional influence | No belonging or multicultural-perspective behavior measurements |
| 3 | November/December 2014 | The same three named relationship items | Behavior items also collected |
| 4 | December 2015 | The same three named relationship items | Separate study consent; some students had left the program |

Each nomination is directed from the reporting person to the named alter. Friendship, academic discussion and professional influence remain separate layers. A self-reported professional-influence nomination is not an identified causal effect. Wave 1 cannot be inserted as an earlier friendship matrix to make a longer panel.

The dictionary provides ordinal items, including `BELONG1`–`BELONG3` on a 1–4 scale and individual M-GUD-S items on a 1–6 scale. It also includes reverse-coded items, composite/subscale scores and continuous attributes, which must retain their own definitions. `-999` is a source missing-value code in these characteristics, not an ordinal observation. Selecting an item or score as a dependent variable requires a declared measurement and research question. The audit does not choose one or generate behavior at wave 2.

## Response, missingness and program membership

The participation dictionary on p. 2 and the edge-list definitions on pp. 22–23 establish separate kinds of information:

| Source value or condition | Audit meaning | It does not establish |
| --- | --- | --- |
| A numeric alter ID | A recorded directed nomination | Complete knowledge of every other dyad |
| Explicit blank `Alter` | The respondent reported no alters for that item | No incoming ties or no ties outside the item roster |
| Literal `NA` in `Alter` | Missing item, from survey nonparticipation or item nonresponse | A zero outgoing row |
| Roster ego entirely omitted from one edge list | No row was supplied for that ego/item | The meaning of either an explicit blank or `NA` |
| Participation status `1` | Survey participation | Completion of every relationship question |
| Participation status `0` | Survey nonparticipation | Departure from the MSW program |
| Participation status `-99` | Not enrolled in the study | Absence from the social network or ineligibility as an alter |
| Wave-4 participation status `10` | Not enrolled in the MSW program | Zero incoming nominations or an exact departure time |

The reviewed participation file has these aggregate counts:

| Wave | Status 1 | Status 0 | Status -99 | Status 10 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 130 | 12 | 3 | Not defined |
| 2 | 142 | 0 | 3 | Not defined |
| 3 | 140 | 2 | 3 | Not defined |
| 4 | 116 | 0 | 25 | 4 |

The four wave-4 status-10 actors have missing outgoing reports in every relationship file. They still receive **14 academic-discussion, 9 friendship and 5 professional-influence nominations**. These known incoming records must survive an audit of their missing outgoing observations. Program membership and eligibility to be named in a social relationship are different variables.

Item coverage also differs among survey participants. The source has one omitted ego in wave-2 friendship and two omitted egos in wave-4 professional influence; all three are marked survey participants. The files additionally contain item-level `NA` among participants. Consequently, a survey response flag cannot substitute for a per-relation outgoing-response mask.

For a future fixed-population adapter, unknown `i→j` and observed `j→i` must be representable simultaneously. Deleting the whole actor or masking both the row and column would discard valid evidence. The present audit preserves this distinction in its aggregates and does not construct an assumed complete matrix.

## Source anomalies and recorded nomination turnover

The reviewed relation files contain **15 self-nomination rows**, one wave-4 academic nomination whose alter is outside the supplied roster, and the three omitted ego/item records described above. These are source findings to resolve or explicitly account for. The audit does not silently drop self-nominations, invent a roster record for an outside alter, or convert an omitted record into an explicit no-ties response.

The longitudinal output uses `persistent`, `first_recorded` and `no_longer_recorded`. They compare the presence of **recorded nominations** in successive files of the same relation and retain disjoint ego-coverage strata. They are not confirmed tie creations or dissolutions. An unrecorded earlier tie could reflect nonresponse, an omitted item or uncertain roster eligibility.

For example, the independent source check counts 653, 730 and 917 within-roster, non-self friendship nominations in waves 2, 3 and 4. The corresponding recorded-nomination counts are:

| Comparison | Persistent | First recorded in later file | No longer recorded in later file |
| --- | ---: | ---: | ---: |
| Wave 2 → 3 | 462 | 268 | 191 |
| Wave 3 → 4 | 412 | 505 | 318 |

These counts are not the CSV row totals: blank, `NA` and self-nomination records have distinct audit roles. The original anomalies remain reported; excluding them from this explicitly defined count does not declare them corrected. Even a comparison restricted to egos with supplied responses at both waves still needs a justified target roster before unlisted dyads can be interpreted as observed zeros.

## Shared-course files are already person–person counts

Dictionary p. 24 defines `SharedCourseAffiliationMatrix.csv` with **people on both axes**. An off-diagonal value counts courses shared by a pair during Fall 2014–Fall 2015; the diagonal records the person's own course count. The companion valued edge list describes the same kind of person-pair quantity. Its naming does not make it a person–activity incidence table.

Course-data `NA` can reflect a missing consent for academic-record release. It does not mean that the pair shared zero courses. The supplied counts lack the identities and attendance incidences of individual courses; they cannot uniquely reconstruct who attended each activity. SocioLab therefore does not feed this matrix into its person–activity projection interface or invent course nodes. The cumulative time window also cannot be silently treated as a baseline exposure for an earlier network observation.

## Pinned estimator limits

The current [joint adapter](coevolution.md) accepts complete, directed, fixed-actor panels with one declared ordinal behavior. The Mauldin audit does not relax that contract. Source inspection of **cusna 0.1.0 at commit `313c3d2623c99ed15c1eb6fe713593c6d3915d1d`** identifies possible future missing-data support and specific restrictions:

| Pinned upstream behavior | Consequence for future admission |
| --- | --- |
| Directed network cells can be missing independently; wave-1 missing cells initialize to zero and later missing cells carry forward | A fixed-actor adapter could preserve an unknown outgoing row and known incoming ties, while reporting the upstream initialization separately from observations |
| Missing-at-either-end dyads are excluded from relevant distances/statistic networks; missing dyads generally remain toggleable in the latent simulation | Masked observations are not a known-zero network and are not a model of the missingness mechanism |
| Behavior supports `NaN`, with mode/backward/carry-forward initialization and effect-specific masks | Missing behavior requires a separately qualified input/profile path; the existing complete-data profile cannot simply be marked complete |
| Behavior centering takes the mean of observed means for each supplied wave | A wholly missing behavior wave, such as inserting wave 2 for the listed behavior measures, produces nonfinite centering; it cannot be silently imputed into a joint fit |
| `SaomData` explicitly rejects dependent behavior together with composition change | A joint model with actual actor entry/exit is unsupported by the pinned implementation |

Network-only composition support is also narrower than arbitrary dated membership. It admits integer wave intervals and selects active egos from period-start membership. A leaver still acts during the transition starting at the final active wave, and incoming ties to inactive alters remain toggleable. Its data preparation may apply an outgoing row's missingness pattern to both directions, changing known incoming values. It must not be used as a shortcut for survey nonresponse. In particular, converting wave-4 status `10` into structural-zero columns would contradict the recorded incoming nominations.

Primary implementation references:

- [Data parsing and masks](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/data.py): lines 27–48 silently clear network diagonals; 63–128 define behavior preprocessing; 182–209 define network initialization and the behavior/composition prohibition; 255–309 implement composition changes; 312–323 and 344–477 define period masks and permitted ties.
- [Estimator wiring](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/mom.py): lines 132–202 pass missingness/composition settings and distinguish rate-target conventions. The documented network-only composition path is unconditional; constructor acceptance alone is not evidence of qualification for another mode.
- [Statistic conventions](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/cusna/saom/stats.py): lines 466–537 and 785–808 mask missing behavior in network effects; 995–1035 apply behavior-statistic and neighbor masks. The `avSim` statistic excludes missing behavior alters from its numerator and neighbor count.
- [Documented data API](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/docs/api.md): missing observations, structural codes and integer composition intervals are separate concepts.

These are implementation capabilities and constraints, not a completed qualification of Mauldin missing-data estimation. The existing s50 CPU checks used complete observations. Upstream's [artificial-missingness reference](https://github.com/artemmaltsev74-techcom/cusna/blob/313c3d2623c99ed15c1eb6fe713593c6d3915d1d/prototype/bench/rsiena_missing.R) is a conditional network-only model; it does not independently validate a joint missing-network/missing-behavior profile. No R or Lean runtime is added here.

## Candidate-cohort checkpoint: 2026-11-28

The [new exact-archive candidate audit](experiments/2026-11-28-recorded-contact/mauldin-candidate-audit.json)
and [standalone audit script](experiments/2026-11-28-recorded-contact/mauldin_candidate_audit.py)
use the paper's full-time cohort description to narrow the population question.
Select source cohorts 1–3, retain original study enrollees, and exclude the
documented wave-4 departure code `10`. This yields candidate counts
**74 → 72 → 70**, with **63 wave-4 survey responses**. Those totals match
[the paper's Sections 2.2 and 2.5](https://www.mdpi.com/2227-7102/12/3/205),
but the exact analytic roster identities have not been independently verified.
The source cohort sizes are 26/23/25, whereas the paper describes 24–26.
Using later departure status to select earlier observations is explicitly a
retrospective survivor-cohort choice.

The candidate wave-4 friendship records contain 56 egos with positive
nominations, four explicit blank responses and **ten literal `NA` responses**.
The paper reports nine missing friendship responses and five students with
no friends. The source discrepancy remains unexplained. Seven of the ten
`NA` egos have wave-4 status `-99` (not enrolled in the study); three have status
`1` (survey participation). These source categories are not reclassified.
Eight unknown-outgoing egos still receive **43 known incoming nominations**
from within the candidate cohort. None is erased, and no unknown response is
reclassified to force the published counts to agree.

Among recorded, within-candidate nonself nominations, the wave-3 same-cohort
fractions are 408/410 for friendship and 843/850 for academic discussion,
rounding to the paper's 99.5% and 99.2%. Wave-4 friendship is 424/541 = 78.373%,
which rounds to 78.4%, not exactly the paper's 78.3%. These partial numerical
agreements are clues about scope, not proof of an identical analytic graph.
Candidate egos also make 52 wave-4 friendship nominations to cohorts 4–6, so
the paper's restricted analysis alone does not settle the target eligibility
of the broader archive.

The checkpoint remains **`NOT_ESTIMABLE`**. No complete graph, longitudinal
panel or model fit is produced. It preserves missing responses, source
self-nominations and out-of-candidate nominations as separate audit findings.
The separate [Hypertext recorded-contact case](recorded-contact-case.md)
completes a bounded descriptive study while these friendship-admission
questions remain open; it does not resolve them.

## Conditions for a later empirical model

The next decision is an explicit analysis specification, followed by adapter qualification. It would need to:

1. Establish the eligible population and nomination roster for the selected relationship and waves, keeping study consent, survey response, item response and program membership separate. A restricted cohort or removal of actors changes the target population and must be declared and justified.
2. Resolve or retain with a specified policy the self-nominations, outside-roster nomination and omitted ego/item records. Every transformation must keep source fingerprints and aggregate exclusion reasons; source anomalies cannot disappear during matrix construction.
3. Select a measured ordinal variable and compatible waves. Wave 2 has no listed behavior measurements, and wave 1's different relationship cannot repair that gap. A wave-3/wave-4 joint candidate still faces missing observations and membership questions.
4. Introduce explicit observation masks without changing the complete-data v1 meaning. Before any empirical fit, use genuine upstream CPU tests to verify asymmetric masks, known incoming preservation, behavior initialization, effective period targets, parameter layout and numerical diagnostics. Preserve all-missing and constant-range failure cases.
5. Qualify the model and missingness assumptions for that study. Numerical convergence, archive hash agreement and a related published analysis do not establish population adequacy, prediction accuracy or causal identification. Joint behavior/composition must remain unsupported unless a verified upstream capability resolves that restriction.

## Reproduce the source checks

The retained evidence is [the aggregate source report](experiments/2026-11-27-mauldin/source-audit.json), [retrieval provenance](experiments/2026-11-27-mauldin/retrieval.json), [independent audit](experiments/2026-11-27-mauldin/independent-audit.json), and [validation record](experiments/2026-11-27-mauldin/validation.json). They document the source-admission decision; they contain no Mauldin model-fit result.

The independent script reads only the participation and relationship files of
the exact source archive. It imports no SocioLab implementation. Reproduce its
counts and the CLI comparison from the repository root:

```bash
python -m sociolab source mauldin inspect /path/to/UTA_Social_Networks_Social_Good.zip > source-audit.json
python docs/experiments/2026-11-27-mauldin/independent_audit.py /path/to/UTA_Social_Networks_Social_Good.zip > independent-audit.json
python docs/experiments/2026-11-27-mauldin/verify_audit.py source-audit.json independent-audit.json
python -m unittest discover -s tests -v
```

The [saved comparison](experiments/2026-11-27-mauldin/verification.json) checks
168 agreements across all ten relationship files, source and roster identity,
known incoming records, and the two friendship comparisons, including their
unknown-response strata. This is a consistency check of source reporting.

The fresh base environment also exposed an existing dependency omission:
NetworkX's `prominent_group` imports pandas, while SocioLab had not declared
it. Seven existing group-selection tests failed with `ModuleNotFoundError`.
This change declares `pandas==2.2.3`; the [initial failure log](experiments/2026-11-27-mauldin/native-tests-before-pandas.log)
and [final native test log](experiments/2026-11-27-mauldin/native-tests.log)
retain that correction. No graph algorithm was replaced or altered.
