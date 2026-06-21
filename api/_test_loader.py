from api.data_loader import load_all, LIVE_FUNDS, LIVE_BLES, STATIC_FUNDS, ALL_FUNDS_LIST
load_all()
print("Live funds:", len(LIVE_FUNDS))
print("Live BLEs:", len(LIVE_BLES))
print("Static:", len(STATIC_FUNDS))
print("All:", len(ALL_FUNDS_LIST))
for fid, f in LIVE_FUNDS.items():
    esc = f.get("escalated_tier") or "-"
    print(" ", f["name"], "|", f["direct_tier"], "->", esc, "|", len(f["bles"]), "BLEs")
