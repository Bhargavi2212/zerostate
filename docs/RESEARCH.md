# ZeroState — prior art and research notes (Oct 31, 2026)

"Verified" = full source read. "Abstract" = abstract/landing page only. Guesses marked.

## 1. Standards and guidance (verified)
- **OSHA 29 CFR 1910.147** — https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.147
  - (b): control-circuit devices (push buttons, selector switches) are *not* energy-isolating devices.
  - (c)(4)(ii)(D): procedure must include testing to verify lockout effectiveness.
  - (d)(5)(i)–(ii): relieve stored energy; if it can re-accumulate, keep verifying until work is done.
  - (d)(6): verify isolation and de-energization before work. (f)(4): shift-change transfer. (c)(6): annual inspection by someone other than the user.
  - Appendix A step 7 (try-out) — written for machines; for process lines the equivalent is bleed-down + watch for build-up.
  - OSHA LOTO update (RIN 1218-AD00) may address computer-based controls; no text yet. https://www.ishn.com/articles/115708-osha-plans-a-lockout-tagout-update-what-computer-based-controls-could-change
- **HSE HSG253 Safe isolation of plant and equipment** — https://books.hse.gov.uk/gempdf/hsg253.pdf
  - ¶172 gauges indicate presence of pressure, not complete depressurisation; check an open vent before breaking in.
  - ¶165/173/175 prove every isolation point; no leakage or build-up within the envelope.
  - ¶168 don't rely on an unproved isolation. ¶174 re-prove after a shift.
  - ¶111–120 isolation hierarchy (positive > DBB > DB > SBB); SBB not a final isolation as a rule.
  - ¶151–153 lock actuated valves / isolate motive power. ¶180–182 passing valves.
  - ¶142/154–155 walk the plant vs P&ID; tag every point. ¶44 common failures. ¶188/196 reinstatement.
  - Boxed example after ¶191: pump "isolated only via software" overridden by a demand signal.
- **PetroSA mechanical isolation procedure** (practitioner): 10-minute zero-build-up test; visually confirm vent flow. https://fuelsindustry.org.za/wp-content/uploads/2023/07/PetroSA-Best-Practice-Sharing-Mechanical-isolation-procedure-2023.pdf
- **HSE offshore isolation findings, Dec 2025**: https://press.hse.gov.uk/2025/12/17/offshore-process-isolation-failures-present-major-accident-hazard-risk
- **CCPS Process Safety Beacon Sept 2019** (BP Amoco: plugged gauge read no pressure): https://aiche.org/sites/default/files/2019-09-Beacon-English.pdf
- Not read (paywalled): ANSI/ASSP Z244.1, CCPS books, Energy Institute / IOGP guidance.

## 2. Incidents used as benchmark scenarios (verified unless noted)
- Tosco Avon 1999, 4 killed — passing valve: https://www.csb.gov/assets/1/6/CSB_Digest_-_Tosco_(Preventive_Maintenance).pdf
- Giant Ciniza 2004 — wrench read "closed" while open; plugged vent: https://www.csb.gov/assets/1/20/Giant_Case_Study.pdf
- BP Amoco Augusta 2001, 3 killed — plugged gauge read zero, verification impossible: https://www.csb.gov/assets/1/20/BP_Investigation_Report.pdf
- Phillips 66 Pasadena 1989, 23 killed — reversed actuator hoses: https://www.hse.gov.uk/Comah/sragtech/casepasadena89.htm
- Formosa Illiopolis 2004, 5 killed — wrong reactor: https://www.ehstoday.com/news/ehs_imp_45745
- Williams Geismar 2013, 2 killed — boxed-in reboiler: https://www.csb.gov/csb-releases-final-case-study-into-2013-explosion-and-fire-at-williams-olefins-plant-in-geismar-louisiana/
- LyondellBasell La Porte 2021; Wacker Charleston 2020 (plan-scoping cases) — csb.gov
- BP Texas City 2005 — lying level indicator: https://ehstoday.com/archive/article/21914025/csb-on-refinery-blast-alarms-failed-to-alert-bp-operators-of-dangerous-conditions

## 3. Products (vendor pages, marketing)
Isolation/PTW software — none verify isolation against live data or camera (j5 historian interface and Sphera "monitor integrity of critical valves" unclear):
Brady LINK360, Sphera, Yokogawa OpreX CoW, IntelliPERMIT, Hexagon j5, SALUS (LLM writes procedures; manual verification), AWS P&ID agent blog.
Camera vendors — lock/tag presence only, no zero-energy proof: iFactory, Roboflow ("not a safety-rated device"), viAct, Intenseye, Perley Brook, Rockwell patent US11625024B2.
Electrical only: Panduit VeriSafe automated absence-of-voltage tester.
Links in agent notes; e.g. https://roboflow.com/ai/lockout-tagout-verification , https://ifactoryapp.com/ai-vision-camera/ai-vision-lockout-tagout-verification
**Gap (our judgment, broad but not exhaustive search):** no product or paper checks a declared process isolation by cross-checking camera evidence and live plant data with built-in instrument distrust.

## 4. Detection methods
- Same simplified TE model, CUSUM, pressure attacks: Cárdenas et al., AsiaCCS 2011 — https://users.soe.ucsc.edu/~alacarde/papers/asiaccs11.pdf
- Evaluation framing (impact vs time between false alarms): Urbina et al., CCS 2016 — https://users.soe.ucsc.edu/~alacarde/papers/ccs16.pdf
- Point-adjust inflation warning: Kim et al., AAAI 2022 — https://arxiv.org/abs/2109.05257
- Invariants on SWaT: Feng et al., NDSS 2019 — https://dev.ndss-symposium.org/wp-content/uploads/2019/02/ndss2019_07A-3_Feng_paper.pdf
- PASAD: https://github.com/rahulrajpl/PyPASAD (MIT)
- QARTOD sensor tests (flat line, rate, range): https://cdn.ioos.noaa.gov/media/2020/03/QARTOD_TS_Manual_Update2_200324_final.pdf
- Data reconciliation tests: Bagajewicz, FOCAPO 2003 — https://skoge.folk.ntnu.no/prost/proceedings/focapo_2003/pdffiles/papers/011.pdf
- GRFICS paper: Formby et al., USENIX ASE 2018 — https://cap.ece.gatech.edu/papers/formby_usenix18_grfics.pdf . We found no published detection evaluation on GRFICS (guess, not exhaustive).

## 5. AI side
- MeasureBench (CVPR 2026): digital readouts 80.2% real vs dials ~31%; thinking/prompting barely help. https://arxiv.org/html/2510.26865v2
- Lost in Motion: VLMs output flat lines while needles move; recommend deterministic validation. https://arxiv.org/html/2604.22829v3
- MLLMs Know Where to Look: accuracy depends causally on subject size (crop/zoom). https://arxiv.org/abs/2502.17422 (abstract)
- SAM 3: 15.2 AP zero-shot vs 36.5 AP 10-shot on specialised domains. https://arxiv.org/html/2511.16719v2
- VLM confidence poorly calibrated: https://arxiv.org/abs/2405.02917 (abstract)
- LLM HAZOP: F1 > 86% but only 19–37% semantically valid scenarios (Lee et al., Safety Science 2026, abstract). HAZOP tools review: https://www.icheme.org/media/27631/hazards-34-paper-175-elhosary-revised.pdf
- FaultExplainer (TEP + LLM): https://arxiv.org/html/2412.14492v1
- Validator/reprompt loops: Vyas & Mercangöz https://arxiv.org/html/2411.05904v1 ; LLM4PLC https://arxiv.org/html/2401.05443v1 ; SemaPLC (aggregator summary) ; AgentSpec https://arxiv.org/abs/2503.18666 ; RoboGuard https://arxiv.org/abs/2503.07885
- Agents 102 workshop notes (participant): https://github.com/abelxmendoza/hackathon-day-2-agents-101-legal-agent-workshop

## 6. Competing hackathon entries (from ~89 public repos read Oct 31)
No process-plant / GRFICS / LOTO-verification entry found. Evidence bar set by: GridXray (Startup) https://github.com/jcamiloaa/gridxray ; Mechanical Muse (Indie) https://github.com/jscott3201/mechanical-muse ; proofstep https://github.com/desilva23/proofstep . "Model proposes, code decides" is common — not our differentiator.

## 7. Added Oct 31 — real isolation practice, standards, building blocks, test plants
Isolation practice and incidents
- HSE HSG253 (proving, categories, ¶115, ¶165–182): https://books.hse.gov.uk/gempdf/hsg253.pdf
- OSHA 1910.147 + App A: https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.147
- Chevron isolation standard: https://jopcontractors.chevron.com/EHS/Cow/Isolation%20of%20Hazardous%20Energy%20CoW%20Technical%20Standard.pdf
- Hanford DOE-0336 LOTO (VICs): https://www.hanford.gov/files.cfm/DOE-0336_Rev_4_LOTO.pdf
- PetroSA isolation procedure: https://fuelsindustry.org.za/wp-content/uploads/2023/07/PetroSA-Best-Practice-Sharing-Mechanical-isolation-procedure-2023.pdf
- Seqwater isolation certificate: https://seqwater.com.au/document/595 ; NPDC procedure: https://www.npdc.govt.nz/media/fcfjhonv/npdc-isolations-procuedre.pdf
- WMC MHS-07: https://safteng.net/images/Guideline_Mechanical_and_Process_Isolations_Major_Hazard_Standard.pdf
- IChemE LPB 250 (proving isolations): https://www.icheme.org/media/2086/lpb250pg07.pdf
- SLAC alternative methods under Z244.1: https://www-esh.slac.stanford.edu/eshmanual/references/coheReqAltMethod.pdf
- CSB LyondellBasell 2021: https://www.csb.gov/assets/1/6/lyb_final_report_2023-05-25.pdf ; Williams 2013: https://www.csb.gov/csb-releases-final-case-study-into-2013-explosion-and-fire-at-williams-olefins-plant-in-geismar-louisiana/ ; Tosco: https://www.csb.gov/assets/1/20/Tosco_Digest.pdf ; Pemex: https://www.csb.gov/us-chemical-safety-board-releases-investigation-update-into-fatal-hydrogen-sulfide-release-at-pemex-deer-park-refinery-in-deer-park-texas/ ; Clairton: https://www.csb.gov/us-chemical-safety-board-releases-update-on-its-investigation-of-fatal-explosion-at-us-steel-clairton-coke-works/
- OSHA top-10 FY2025: https://ohsonline.com/articles/2025/09/16/osha-reveals-2025-top-10-most-cited-standards.aspx ; AIChE 100-incident study: https://proceedings.aiche.org/conferences/aiche-spring-meeting-and-global-congress-on-process-safety/2022/proceeding/paper/53ac-reckless-operation-and-maintenance-process-industry-causes-and-prevention-guidelines-study-100
Accepted automated verification
- NFPA 70E AVT exception: https://www.ecmag.com/magazine/articles/article-detail/safety-verifying-absence-voltage-two-new-exceptions-2018-nfpa-70e ; UL 1436 update: https://iaeimagazine.org/issue/2021-march-april/absence-of-voltage-testing-an-update-on-accepted-approaches/
Regulation / AI-in-OT
- CISA/ACSC AI in OT principles (Dec 2025): https://www.cyber.gov.au/business-government/secure-design/operational-technology-environments/principles-for-the-secure-integration-of-artificial-intelligence-in-operational-technology
- IEC 61511 & AI (Kenexis): https://www.kenexis.com/artificial-intelligence-in-safety-systems-is-coming/ ; EU AI Act omnibus: https://www.whitecase.com/insight-alert/eu-ai-omnibus-enters-force-amending-ai-act ; Annex III: https://artificialintelligenceact.eu/annex/3/ ; Art 14: https://artificialintelligenceact.eu/article/14/
- HSE on AI (Jun 2026): https://press.hse.gov.uk/2026/06/12/hses-regulatory-approach-to-artificial-intelligence-ai/
Commercial data models
- SAP WCM operational WCD: https://help.sap.com/saphelp_470/helpdata/en/30/12701746b611d4a7850060087a7a74/content.htm ; Maximo isolation certificates: https://www.ibm.com/docs/en/SS5GME_cd/hse/plusgiso/c_isol_cert_oview.html ; CTRL WRK: https://www.businesswire.com/news/home/20250602395379/en
Building blocks
- pyDEXPI (AGPL-3.0): https://github.com/process-intelligence-research/pyDEXPI ; asyncua: https://github.com/FreeOpcUa/opcua-asyncio ; pymodbus: https://github.com/pymodbus-dev/pymodbus ; ioos_qc: https://github.com/ioos/ioos_qc ; WNTR: https://github.com/USEPA/WNTR
Test plants
- CybICS: https://github.com/mniedermaier/CybICS ; tep-studio: https://github.com/khalidlabs/tep-studio ; OpenModelica OPC UA: https://ecp.ep.liu.se/index.php/modelica/article/download/197/157
Field evidence on AI in safety
- MeasureBench: https://arxiv.org/html/2510.26865v1 ; Beyond Tennessee Eastman (sim-to-real): https://psecommunity.org/wp-content/plugins/wpor/includes/file/2606/LAPSE-2026.0419-1v1.pdf ; Wickens 2015 automation bias: https://drivingresearch.pages.dev/catalog/wickens-2015-complacency-and-automation-bias-in-the-use-of-imperfect-automation/ ; Stanford methane blind tests: https://eao.stanford.edu/publications/detection-technology-benchmarking/comparing-continuous-methane-monitoring-technologies
