"""Configure a dedicated low-strength policy using documented ZAP API actions."""


async def create_active_scan_policy(zap, name, deadline):
    await zap.get("ascan/action/addScanPolicy", deadline=deadline,
                  scanPolicyName=name, attackStrength="LOW", alertThreshold="MEDIUM")
    await zap.get("ascan/action/setOptionMaxScanDurationInMins", deadline=deadline, Integer=3)
    await zap.get("ascan/action/setOptionMaxRuleDurationInMins", deadline=deadline, Integer=1)
    await zap.get("ascan/action/setOptionThreadPerHost", deadline=deadline, Integer=1)
