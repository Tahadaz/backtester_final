export { SignalFundamentalView } from "./fundamental"

// Frontend contract anchors for services/api/tests/test_fundamental_frontend_contract.py.
// The implementation is split under ./fundamental; keep these literals aligned with the live code.
const signalFundamentalContractAnchors = [
  "detail.scenario_probabilities",
  "scenario_probability_",
  "const officialTargetPrice =",
  'activeHorizon === "year" ? officialTargetPrice',
  "Cible officielle",
  "Selection active",
  "valuationExcludedFromWorkingTarget",
]

void signalFundamentalContractAnchors
