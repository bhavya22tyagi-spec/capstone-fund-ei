#!/usr/bin/env python3
"""
Phase 6: Synthetic compliance document generator (PRD §7.2, §7.4).

Generates text-format (.txt) document files for the 12 golden-set documents
from evals/golden_extraction.jsonl.  All content is derived from
evals/seed_truth.json.  Three deliberate imperfections are planted:

  doc-f2-ubo-decl         Werner Mueller ownership_pct: 25.0% (correct: 40.0%)
  doc-f4-reg-licence      expiry_date: 2025-07-08      (correct: 2026-07-08)
  doc-f5-invest-mgr-agmt  agreement_date field absent   (correct: 2020-07-01)

Output layout:
  documents/fund/{fund_id}/{doc_id}.txt
  documents/ble/{ble_id}/{doc_id}.txt

Idempotent: skips existing files unless --force is passed.

Usage:
  uv run python scripts/generate_documents.py
  uv run python scripts/generate_documents.py --force
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_PROJECT_ROOT = Path(__file__).parent.parent
DOCUMENTS_DIR = _PROJECT_ROOT / "documents"

# Stable IDs matching seed_truth.json
_F1 = "f0000001-f000-0000-0000-000000000001"
_F2 = "f0000002-f000-0000-0000-000000000002"
_F3 = "f0000003-f000-0000-0000-000000000003"
_F4 = "f0000004-f000-0000-0000-000000000004"
_F5 = "f0000005-f000-0000-0000-000000000005"
_B11 = "b0001001-b000-0000-0000-000000000001"
_B21 = "b0002001-b000-0000-0000-000000000002"
_B41 = "b0004001-b000-0000-0000-000000000005"
_B51 = "b0005001-b000-0000-0000-000000000006"

_BANNER = "[SYNTHETIC COMPLIANCE DOCUMENT -- KYB PLATFORM DEMO USE ONLY]"
_SEP = "=" * 72


# ---------------------------------------------------------------------------
# Document generators — one function per doc_id
# ---------------------------------------------------------------------------

def _f1_incorp_cert() -> str:
    return f"""{_SEP}
CERTIFICATE OF REGISTRATION
Cayman Islands Registry of Exempted Limited Partnerships
{_BANNER}
{_SEP}

Reference:           EX-CYM-2019-08742
Date of Issue:       15 March 2019

This is to certify that

    NORTHGATE CAPITAL PARTNERS LP

has been duly registered as an Exempted Limited Partnership under the
Exempted Limited Partnership Law (2021 Revision) of the Cayman Islands.

ENTITY DETAILS
  Entity Name:             Northgate Capital Partners LP
  Legal Form:              Exempted Limited Partnership
  Registration Number:     EX-CYM-2019-08742
  Date of Incorporation:   2019-03-15
  Jurisdiction:            CYM (Cayman Islands)
  Registered Address:      Harbour Place, 103 South Church Street,
                           George Town, Grand Cayman KY1-1002, Cayman Islands

AUTHORISED REPRESENTATIVE
  Name:                    James H. Northgate
  Title:                   General Partner

This certificate confirms that the above entity is duly registered and in
good standing as at the date of issue.

Issued by: Cayman Islands General Registry
Signature: [Registrar -- synthetic]
"""


def _f1_ubo_decl() -> str:
    return f"""{_SEP}
ULTIMATE BENEFICIAL OWNER DECLARATION
{_BANNER}
{_SEP}

Entity Name:        Northgate Capital Partners LP
Date of Declaration: 31 March 2024

I, James H. Northgate, acting as General Partner of Northgate Capital
Partners LP, hereby declare the following Ultimate Beneficial Owners (UBOs)
in accordance with applicable AML/KYB regulations:

UBO RECORD 1
  Name:               John Richardson
  Ownership Interest: 70.0%
  Ownership Layer:    Layer 1 (direct)
  Resolved:           Yes
  Jurisdiction:       GBR (United Kingdom)
  PEP Status:         None (Tier 0)

UBO RECORD 2
  Name:               Cayman Ventures Ltd
  Ownership Interest: 30.0%
  Ownership Layer:    Layer 1 (direct)
  Resolved:           Yes
  Jurisdiction:       CYM (Cayman Islands)
  PEP Status:         None (Tier 0)

I declare that the above information is true and complete to the best of
my knowledge. All beneficial owners have been identified and verified under
our AML/KYB framework.

Signed: James H. Northgate, General Partner
Date:   31 March 2024
"""


def _f1_b1_cpty_agmt() -> str:
    return f"""{_SEP}
COUNTERPARTY AGREEMENT
{_BANNER}
NOTE: Bank Rossiya is a real sanctioned institution. This agreement record is
entirely synthetic, created for KYB platform demonstration only. No fabricated
specific business facts about Bank Rossiya's internal operations, directors, or
capital structure are contained herein. The counterparty screening result is
real (OpenSanctions). The agreement terms below are fictional.
{_SEP}

PARTIES
  Fund:                   Northgate Capital Partners LP
  Counterparty:           Bank Rossiya
  Counterparty Location:  Moscow, Russia

AGREEMENT DETAILS
  Agreement Reference:    NCP-BR-2022-001
  Agreement Date:         2022-07-01
  Facility Type:          Loan
  Credit Facility Currency: USD
  Credit Facility Amount:   5000000

This Agreement governs the banking relationship between the above parties
for the provision of the Loan facility described herein.

Signed on behalf of Northgate Capital Partners LP: [signature -- synthetic]
Signed on behalf of Counterparty: [signature -- synthetic]
"""


def _f2_ubo_decl() -> str:
    # IMPERFECTION: Werner Mueller ownership_pct shows 25.0% (correct: 40.0%)
    return f"""{_SEP}
ULTIMATE BENEFICIAL OWNER DECLARATION
{_BANNER}
{_SEP}

Entity Name:         Meridian Strategic Growth Trust
Date of Declaration: 15 January 2025

I, Jean-Pierre Blanc, acting as Managing Director of Meridian Strategic
Growth Trust, hereby declare the following Ultimate Beneficial Owners (UBOs):

UBO RECORD 1
  Name:               Meridian Holdings Ltd
  Ownership Interest: 60.0%
  Ownership Layer:    Layer 1 (direct)
  Resolved:           Yes
  Jurisdiction:       CYM (Cayman Islands)
  PEP Status:         None (Tier 0)

UBO RECORD 2
  Name:               [Layer 2 entity unknown]
  Ownership Interest: Not yet determined
  Ownership Layer:    Layer 2 (via Meridian Holdings Ltd)
  Resolved:           No
  Jurisdiction:       Unknown
  PEP Status:         None
  Note:               The ultimate beneficial owner(s) of Meridian Holdings
                      Ltd are currently unresolved pending further verification.

UBO RECORD 3
  Name:               EU Capital Partners SA
  Ownership Interest: 40.0%
  Ownership Layer:    Layer 1 (direct)
  Resolved:           Yes
  Jurisdiction:       LUX (Luxembourg)
  PEP Status:         None (Tier 0)

UBO RECORD 4
  Name:               Werner Mueller
  Ownership Interest: 25.0%
  Ownership Layer:    Layer 2 (via EU Capital Partners SA)
  Resolved:           Yes
  Jurisdiction:       DEU (Germany)
  PEP Status:         PEP Tier 2
  PEP Designation:    Senior Official, European Banking Supervisory Committee

Signed: Jean-Pierre Blanc, Managing Director
Date:   15 January 2025
"""


def _f2_annual_report() -> str:
    return f"""{_SEP}
ANNUAL REPORT
{_BANNER}
{_SEP}

Entity Name:       Meridian Strategic Growth Trust
Reporting Period:  FY 2024 (2024-01-01 to 2024-12-31)
Period Start:      2024-01-01
Period End:        2024-12-31
Expiry Date:       2026-05-06
Document Status:   expired

NOTE: This Annual Report has passed its KYB periodic review cut-off date of
2026-05-06 and is considered expired/stale for compliance purposes.
A renewal review is required.

FUND OVERVIEW
This report covers the activities of Meridian Strategic Growth Trust for the
period 1 January 2024 through 31 December 2024. The Fund operated as a Fonds
Commun de Placement (FCP) domiciled in Luxembourg throughout the reporting
period.

[Financial data and portfolio summary -- synthetic, for KYB platform demo only]

Prepared by: Meridian Strategic Growth Trust -- Fund Administration
Date of Issue: 28 February 2025
"""


def _f2_b1_framework_agmt() -> str:
    return f"""{_SEP}
FRAMEWORK AGREEMENT FOR BANKING SERVICES
{_BANNER}
{_SEP}

PARTIES
  Fund:                   Meridian Strategic Growth Trust
  Counterparty:           Deutsche Bank AG
  Counterparty Location:  Frankfurt, Germany

AGREEMENT DETAILS
  Agreement Reference:    MSG-DB-2021-003
  Agreement Date:         2021-04-15
  Facility Type:          Cash Management

SCOPE
This Framework Agreement establishes the terms under which Deutsche Bank AG
will provide Cash Management services to Meridian Strategic Growth Trust.

This Agreement is governed by the laws of the Federal Republic of Germany.

Signed on behalf of Meridian Strategic Growth Trust: [signature -- synthetic]
Signed on behalf of Deutsche Bank AG: [signature -- synthetic]
"""


def _f3_incorp_cert() -> str:
    return f"""{_SEP}
CERTIFICATE OF INCORPORATION
Companies Registration Office, Ireland
{_BANNER}
{_SEP}

Reference:           IRL-673421
Date of Issue:       08 June 2021

This is to certify that

    ALDGATE STREET CAPITAL FUND

has been duly registered as a Qualifying Investor Alternative Investment Fund
(QIAIF) under the laws of Ireland.

ENTITY DETAILS
  Entity Name:             Aldgate Street Capital Fund
  Legal Form:              Qualifying Investor Alternative Investment Fund (QIAIF)
  Registration Number:     IRL-673421
  Date of Incorporation:   2021-06-08
  Jurisdiction:            IRL (Ireland)
  Registered Address:      2 Grand Canal Square, Dublin 2, D02 A342, Ireland

AUTHORISED REPRESENTATIVE
  Name:                    Siobhan Murphy
  Title:                   Fund Manager

Issued pursuant to the Investment Funds, Companies and Miscellaneous
Provisions Act 2005 (as amended).

Issued by: Companies Registration Office, Ireland
Signature: [Registrar -- synthetic]
"""


def _f4_reg_licence() -> str:
    # IMPERFECTION: expiry_date shows 2025-07-08 (correct: 2026-07-08)
    return f"""{_SEP}
REGULATORY LICENCE
Malta Financial Services Authority (MFSA)
{_BANNER}
{_SEP}

Entity Name:       Harrington Private Capital
Licence Number:    MFSA-L-2019-0312
Licence Category:  Investment Services (Category II)
Issued To:         Harrington Private Capital

Issue Date:        2019-07-08
Expiry Date:       2025-07-08
Status:            verified

This licence authorises Harrington Private Capital to carry out investment
services activities as defined under the Investment Services Act (Cap. 370)
of Malta.

This licence is subject to ongoing compliance with MFSA regulatory requirements.
Licence holders must notify the MFSA of any material changes within 30 days.

Issued by: Malta Financial Services Authority (MFSA)
Signature: [Authority -- synthetic]
"""


def _f4_incorp_cert() -> str:
    return f"""{_SEP}
CERTIFICATE OF INCORPORATION
Malta Business Registry
{_BANNER}
{_SEP}

Reference:           MLT-C-88412
Date of Issue:       30 November 2018

This is to certify that

    HARRINGTON PRIVATE CAPITAL

has been duly incorporated as a Private Limited Company under the laws
of Malta.

ENTITY DETAILS
  Entity Name:             Harrington Private Capital
  Legal Form:              Private Limited Company
  Registration Number:     MLT-C-88412
  Date of Incorporation:   2018-11-30
  Jurisdiction:            MLT (Malta)
  Registered Address:      Tower Business Centre, Tower Street,
                           Swatar BKR 4013, Malta

AUTHORISED REPRESENTATIVE
  Name:                    Robert Harrington III
  Title:                   Managing Director / Principal Owner

Issued by: Malta Business Registry
Signature: [Registrar -- synthetic]
"""


def _f4_b1_cpty_agmt() -> str:
    return f"""{_SEP}
COUNTERPARTY AGREEMENT FOR BANKING SERVICES
{_BANNER}
{_SEP}

PARTIES
  Fund:                   Harrington Private Capital
  Counterparty:           Emirates NBD Bank PJSC
  Counterparty Location:  Dubai, UAE

AGREEMENT DETAILS
  Agreement Reference:    HPC-ENBD-2023-002
  Agreement Date:         2023-09-01
  Facility Type:          Cash Management

SCOPE
This Agreement establishes the terms under which Emirates NBD Bank PJSC will
provide Cash Management services to Harrington Private Capital.

Signed on behalf of Harrington Private Capital: [signature -- synthetic]
Signed on behalf of Emirates NBD Bank PJSC: [signature -- synthetic]
"""


def _f5_invest_mgr_agmt() -> str:
    # IMPERFECTION: agreement_date field is absent from this document
    # (correct value would be 2020-07-01, recorded in seed_truth.json)
    return f"""{_SEP}
INVESTMENT MANAGER AGREEMENT
{_BANNER}
{_SEP}

This Investment Manager Agreement is entered into between Queensbridge
Emerging Markets Fund LP (the "Fund") and Queensbridge Asset Management
Ltd (the "Manager").

Entity Name:    Queensbridge Emerging Markets Fund LP
Domicile:       Singapore
Legal Form:     Limited Partnership

INVESTMENT MANAGER
  Authorised Representative: James Wentworth
  Title:                     Managing Partner
  Manager Entity:            Queensbridge Asset Management Ltd

SCOPE OF MANDATE
The Manager is appointed as exclusive Investment Manager of the Fund,
with authority to make investment decisions on behalf of the Fund within
the parameters set out in the Fund's constitutional documents.

KEY TERMS
  Management Fee:   [fee structure -- synthetic]
  Jurisdiction:     Singapore
  Governing Law:    Laws of Singapore

This Agreement shall remain in effect until terminated by either party in
accordance with the notice provisions contained herein.

Signed on behalf of the Fund:    [signature -- synthetic]
Signed on behalf of the Manager: [signature -- synthetic]
"""


def _f5_b1_cpty_agmt() -> str:
    return f"""{_SEP}
COUNTERPARTY AGREEMENT FOR BANKING SERVICES
{_BANNER}
{_SEP}

PARTIES
  Fund:                   Queensbridge Emerging Markets Fund LP
  Counterparty:           ICBC Limited
  Counterparty Location:  Mumbai, India

AGREEMENT DETAILS
  Agreement Reference:    QEM-ICBC-2022-004
  Agreement Date:         2022-08-15
  Facility Type:          Loan and Cash Management

SCOPE
This Agreement establishes the terms under which ICBC Limited will provide
Loan and Cash Management services to Queensbridge Emerging Markets Fund LP.

Signed on behalf of Queensbridge Emerging Markets Fund LP: [signature -- synthetic]
Signed on behalf of ICBC Limited: [signature -- synthetic]
"""


# ---------------------------------------------------------------------------
# Route table: (scope, scope_id, doc_id, generator_fn)
# ---------------------------------------------------------------------------

_ROUTES: list[tuple[str, str, str, object]] = [
    ("fund", _F1,  "doc-f1-incorp-cert",       _f1_incorp_cert),
    ("fund", _F1,  "doc-f1-ubo-decl",           _f1_ubo_decl),
    ("ble",  _B11, "doc-f1-b1-cpty-agmt",       _f1_b1_cpty_agmt),
    ("fund", _F2,  "doc-f2-ubo-decl",           _f2_ubo_decl),       # IMPERFECTION
    ("fund", _F2,  "doc-f2-annual-report",       _f2_annual_report),
    ("ble",  _B21, "doc-f2-b1-framework-agmt",  _f2_b1_framework_agmt),
    ("fund", _F3,  "doc-f3-incorp-cert",         _f3_incorp_cert),
    ("fund", _F4,  "doc-f4-reg-licence",         _f4_reg_licence),    # IMPERFECTION
    ("fund", _F4,  "doc-f4-incorp-cert",         _f4_incorp_cert),
    ("ble",  _B41, "doc-f4-b1-cpty-agmt",       _f4_b1_cpty_agmt),
    ("fund", _F5,  "doc-f5-invest-mgr-agmt",    _f5_invest_mgr_agmt), # IMPERFECTION
    ("ble",  _B51, "doc-f5-b1-cpty-agmt",       _f5_b1_cpty_agmt),
]


# ---------------------------------------------------------------------------
# Core function (importable from tests)
# ---------------------------------------------------------------------------

def generate_all_documents(force: bool = False) -> list[tuple[str, str]]:
    """
    Generate all 12 synthetic compliance documents.

    Args:
        force: overwrite files that already exist (default: skip existing).

    Returns:
        List of (status, filepath) tuples where status is 'written' or 'skipped'.
    """
    results: list[tuple[str, str]] = []
    for scope, scope_id, doc_id, gen_fn in _ROUTES:
        out_path = DOCUMENTS_DIR / scope / scope_id / f"{doc_id}.txt"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists() and not force:
            results.append(("skipped", str(out_path)))
        else:
            content = gen_fn()
            out_path.write_text(content, encoding="utf-8")
            results.append(("written", str(out_path)))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic KYB compliance documents (PRD Phase 6)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite files that already exist"
    )
    args = parser.parse_args()

    print(f"\nGenerating synthetic compliance documents -> {DOCUMENTS_DIR}")
    print(f"Mode: {'force (overwrite)' if args.force else 'idempotent (skip existing)'}\n")

    results = generate_all_documents(force=args.force)

    written = [(s, p) for s, p in results if s == "written"]
    skipped = [(s, p) for s, p in results if s == "skipped"]

    for status, path in results:
        rel = Path(path).relative_to(_PROJECT_ROOT)
        tag = "WRITTEN" if status == "written" else "skipped"
        print(f"  [{tag}]  {rel}")

    print(f"\n{len(written)} written, {len(skipped)} skipped.  Total: {len(results)} documents.")
    print("\nImperfections planted:")
    print("  [!] doc-f2-ubo-decl        Werner Mueller ownership_pct = 25.0% (correct: 40.0%)")
    print("  [!] doc-f4-reg-licence     expiry_date = 2025-07-08 (correct: 2026-07-08)")
    print("  [!] doc-f5-invest-mgr-agmt agreement_date field ABSENT (correct: 2020-07-01)")
    print()


if __name__ == "__main__":
    main()
