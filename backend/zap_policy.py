"""Configure a dedicated low-strength policy using documented ZAP API actions."""

# These rules change scheme/port, target internal metadata, or test availability.
# They do not belong in the bounded exact-origin staging profile.
EXCLUDED_ACTIVE_RULES = (10047, 90034, 40044)

async def create_active_scan_policy(zap, name, deadline):
    await zap.get("ascan/action/addScanPolicy", deadline=deadline,
                  scanPolicyName=name, attackStrength="LOW", alertThreshold="MEDIUM")
    await zap.get("ascan/action/setOptionMaxScanDurationInMins", deadline=deadline, Integer=3)
    await zap.get("ascan/action/setOptionMaxRuleDurationInMins", deadline=deadline, Integer=1)
    await zap.get("ascan/action/setOptionThreadPerHost", deadline=deadline, Integer=1)
    await zap.get("ascan/action/disableScanners", deadline=deadline,
                  scanPolicyName=name, ids=",".join(map(str, EXCLUDED_ACTIVE_RULES)))
