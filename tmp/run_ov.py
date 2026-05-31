from playwright.sync_api import sync_playwright
import os
H = "file://" + os.path.abspath("tmp/ov_harness.html")
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(H); pg.wait_for_timeout(200)
    out = pg.evaluate("""() => {
      renderOverview(window.__sample);
      return {
        venMark: document.getElementById('ov-ven-mark').className,
        blockedMark: document.getElementById('ov-blocked-mark').className,
        ven: document.getElementById('ov-ven-body').innerText,
        blocked: document.getElementById('ov-blocked-body').innerText
      };
    }""")
    b.close()
print(out); print("errs:", errs or "none")
assert "warn" in out["venMark"] and "ok" in out["blockedMark"], f"mark classes wrong: {out}"
assert "19/21" in out["ven"], f"VEN body wrong: {out['ven']}"
assert "1,290" in out["blocked"] or "1290" in out["blocked"], f"blocked body wrong: {out['blocked']}"
print("PASS")
