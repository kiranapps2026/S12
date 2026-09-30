"""M15 sabotage: the model's answer is read loosely, so "PASS -- confident" passes (D6: the strict enum, anything
malformed is UNKNOWN)."""
def apply():
    from engine.stages.s13_reconciliation import verification

    def parse_semantic(raw):
        text = str(raw or "").upper()
        return "PASS" if "PASS" in text else ("FAIL" if "FAIL" in text else "UNKNOWN")
    verification.parse_semantic = parse_semantic
