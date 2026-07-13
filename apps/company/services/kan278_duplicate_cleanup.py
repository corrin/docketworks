"""Finite, human-reviewed KAN-278 cleanup for the production dataset.

The decisions below are data, not matching rules.  Every production candidate was
reviewed and is either in a named merge decision or in a named retained decision.
No database identity is embedded here: database IDs are resolved only after the
human-readable evidence has been checked against the database.
"""

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.company_merge_service import merge_companies
from apps.company.services.duplicate_identity_report import (
    DuplicateIdentityReportService,
)
from apps.company.services.person_merge_service import merge_people


@dataclass(frozen=True)
class CompanyMergeDecision:
    canonical_name: str
    names: tuple[str, ...]
    expected_rows: int
    evidence: str


@dataclass(frozen=True)
class PersonSelector:
    name: str
    email: str | None
    company_name: str | None


@dataclass(frozen=True)
class PersonMergeDecision:
    canonical: PersonSelector
    members: tuple[PersonSelector, ...]
    expected_people: int
    evidence: str


@dataclass(frozen=True)
class RetainedDecision:
    names: tuple[str, ...]
    evidence: str


@dataclass(frozen=True)
class InvalidLinkDecision:
    company_name: str
    person_name: str
    person_email: str | None
    evidence: str


REVIEWED_COMPANY_MERGES: tuple[CompanyMergeDecision, ...] = (
    CompanyMergeDecision(
        canonical_name="2Talk Limited",
        names=("2Talk", "2Talk Limited"),
        expected_rows=2,
        evidence="production jobs 2Talk=0, 2Talk Limited=0",
    ),
    CompanyMergeDecision(
        canonical_name="acryfab",
        names=("acryfab", "CASH SALE - BLAYNE NEWTON"),
        expected_rows=2,
        evidence="production jobs acryfab=1, CASH SALE - BLAYNE NEWTON=1; shared contact blayne newton; shared email blayne@acryfab.co.nz; shared email domain acryfab.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Actual Building Services",
        names=("Actual Building Services", "CASH SALE - SHANE ANNISS"),
        expected_rows=2,
        evidence="production jobs Actual Building Services=0, CASH SALE - SHANE ANNISS=1; shared email shane.anniss@xtra.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Aesthetix",
        names=("Aesthetix", "Priel Segev"),
        expected_rows=2,
        evidence="production jobs Aesthetix=3, Priel Segev=0; shared email domain aesthetix.co.nz; shared email priel@aesthetix.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Archer Hospitality",
        names=("Archer Hospitality", "Lionel Don"),
        expected_rows=2,
        evidence="production jobs Archer Hospitality=0, Lionel Don=1; shared email domain archerconcepts.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Assa Abloy - Entrance Systems Ltd",
        names=("Assa Abloy - Entrance Systems Ltd", "Davis"),
        expected_rows=2,
        evidence="production jobs Assa Abloy - Entrance Systems Ltd=0, Davis=0; shared email domain assaabloy.com",
    ),
    CompanyMergeDecision(
        canonical_name="B C Hastings",
        names=("B C Hastings", "Brian Hastings", "CASH - SALE - BRIAN HASTINGS"),
        expected_rows=3,
        evidence="production jobs B C Hastings=0, Brian Hastings=1, CASH - SALE - BRIAN HASTINGS=0; shared email billieh@xtra.co.nz; shared phone +64221770482",
    ),
    CompanyMergeDecision(
        canonical_name="Bad Girl Creek Production",
        names=("Bad Girl Creek Production", "Manu One Limited - account closed"),
        expected_rows=2,
        evidence="production jobs Bad Girl Creek Production=0, Manu One Limited - account closed=0; shared email gmills989@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Bikaner Foods",
        names=("Bikaner Foods", "CASH SALE - ASHOKA SHARMA"),
        expected_rows=2,
        evidence="production jobs Bikaner Foods=0, CASH SALE - ASHOKA SHARMA=1; shared email ashoknz@yahoo.com; shared email domain yahoo.com",
    ),
    CompanyMergeDecision(
        canonical_name="Blackstone Project Management",
        names=("Blackstone Project Management", "Bobby Prajito"),
        expected_rows=2,
        evidence="production jobs Blackstone Project Management=3, Bobby Prajito=0; shared email bobby@blackstonepm.co.nz; shared email domain blackstonepm.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="C V Compton Ltd",
        names=("C V Compton Ltd", "Onsite Mechanics NZ Ltd"),
        expected_rows=2,
        evidence="production jobs C V Compton Ltd=1, Onsite Mechanics NZ Ltd=1; shared email domain cvcompton.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Camson Hoist Hire Limited",
        names=("Camson Hoist Hire Limited", "CASH SALE - Lift truck"),
        expected_rows=2,
        evidence="production jobs Camson Hoist Hire Limited=0, CASH SALE - Lift truck=1; shared email domain liftrucks.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - Alex McCormick",
        names=("CASH SALE - Alex McC", "CASH SALE - Alex McCormick"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Alex McC=0, CASH SALE - Alex McCormick=0; shared phone +64226160300",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - ASSET FORCE",
        names=("CASH SALE - ASSET FORCE", "CASH SALE - ONE STOP CUTTING SHOP"),
        expected_rows=2,
        evidence="production jobs CASH SALE - ASSET FORCE=2, CASH SALE - ONE STOP CUTTING SHOP=1; shared email domain assetforce.co.nz; shared email jonas@assetforce.co.nz; shared phone +64277562134",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - AZ PANELS REPAIRS",
        names=("Azam 021677855", "CASH SALE - AZ PANELS REPAIRS"),
        expected_rows=2,
        evidence="production jobs Azam 021677855=1, CASH SALE - AZ PANELS REPAIRS=1; shared phone +6421677855",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - BRONWYN JACKSON",
        names=("Bronnie 02102255430", "CASH SALE - BRONWYN JACKSON"),
        expected_rows=2,
        evidence="production jobs Bronnie 02102255430=1, CASH SALE - BRONWYN JACKSON=2; shared phone +642102255430",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - Church Street Panelbeaters",
        names=(
            "CASH SALE - Church St Motors",
            "CASH SALE - CHURCH ST PANELBEATERS",
            "CASH SALE - Church Street Panelbeaters",
        ),
        expected_rows=3,
        evidence="production jobs CASH SALE - Church St Motors=3, CASH SALE - CHURCH ST PANELBEATERS=0, CASH SALE - Church Street Panelbeaters=1; shared contact onkar goundar; shared email church.st.panelbeaters@gmail.com; shared phone +64275670142",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - DAVID BOOTH",
        names=("CASH SALE - Dave Booth", "CASH SALE - DAVID BOOTH"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Dave Booth=1, CASH SALE - DAVID BOOTH=1; shared email carpenterdavebooth@gmail.com; shared phone +642102631588",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - DOT DESIGN SAM GOODRIDGE",
        names=(
            "CASH SALE - DOT DEISIGN DAM GOODRIDGE",
            "CASH SALE - DOT DESIGN SAM GOODRIDGE",
        ),
        expected_rows=2,
        evidence="production jobs CASH SALE - DOT DEISIGN DAM GOODRIDGE=0, CASH SALE - DOT DESIGN SAM GOODRIDGE=1; shared phone +610420355724",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - ELIJAH HARIDAS",
        names=("CASH SALE - ELIJAH HARIDAS",),
        expected_rows=2,
        evidence="production jobs CASH SALE - ELIJAH HARIDAS=0, CASH SALE - ELIJAH HARIDAS=1; shared contact elijah haridas; shared email elijahraulharidas@gmail.com; shared phone +642904302129",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - LIAM GREENWAY",
        names=("CASH - SALE - Liam Greenway", "CASH SALE - LIAM GREENWAY"),
        expected_rows=2,
        evidence="production jobs CASH - SALE - Liam Greenway=1, CASH SALE - LIAM GREENWAY=1; shared email lbgreenway@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - MARCUS SHELLEY",
        names=("CASH SALE - MARCUS SHELLEY", "CASH SALE - MARCUS SHELLY"),
        expected_rows=2,
        evidence="production jobs CASH SALE - MARCUS SHELLEY=1, CASH SALE - MARCUS SHELLY=0; shared email theshelleysnz@gmail.com; shared phone +6421979629",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - MARSH COOPER",
        names=("CASH SALE - MARSH COOPER", "Marsh"),
        expected_rows=2,
        evidence="production jobs CASH SALE - MARSH COOPER=1, Marsh=1; shared phone +6421920315",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - NEW GENERATION OPERATIONS",
        names=(
            "Ariki Gate and Cross Stock Depo",
            "CASH SALE - NEW GENERATION OPERATIONS",
            "Ian Matthew",
        ),
        expected_rows=3,
        evidence="production jobs Ariki Gate and Cross Stock Depo=0, CASH SALE - NEW GENERATION OPERATIONS=1, Ian Matthew=1; shared email annettematthew1970@gmail.com; shared phone +64274754864",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - ONEHUNGA AUTOMOTIVE NZ LTD",
        names=(
            "CASH SALE - ONEHUNGA AUTOMOTIVE NZ LTD",
            "CASH SALE - ONEHUNGA AUTOMOTIVE NZ LTD - JABIL",
        ),
        expected_rows=2,
        evidence="production jobs CASH SALE - ONEHUNGA AUTOMOTIVE NZ LTD=0, CASH SALE - ONEHUNGA AUTOMOTIVE NZ LTD - JABIL=1; shared email oanz202@gmail.com; shared phone +6421803134",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - REM WADEH",
        names=("CASH - SALE - RERM WADEH", "CASH SALE - REM WADEH"),
        expected_rows=2,
        evidence="production jobs CASH - SALE - RERM WADEH=0, CASH SALE - REM WADEH=2; shared contact rem wadeh; shared email rem_wadeh@hotmail.com; shared phone +64211523239",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - RICHARD MATHIESON",
        names=("CASH SALE - REICHARD MATHIESON", "CASH SALE - RICHARD MATHIESON"),
        expected_rows=2,
        evidence="production jobs CASH SALE - REICHARD MATHIESON=0, CASH SALE - RICHARD MATHIESON=1; shared phone +64272787383",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - Richard Pryde",
        names=("CASH SALE - Richard Pryde",),
        expected_rows=2,
        evidence="production jobs CASH SALE - Richard Pryde=1, CASH SALE - Richard Pryde=0",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - Rick Van Swet",
        names=("CASH SALE - Rick Van Swet", "Rick vanderset"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Rick Van Swet=1, Rick vanderset=1; shared phone +6421400711",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - Seran",
        names=("CASH SALE - Seran", "CASH SALE Seran"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Seran=1, CASH SALE Seran=0",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - SUPERCITY COMMERCIAL INTERIORS LTD",
        names=(
            "CASH SALE - Glen Barratt",
            "CASH SALE - SUPERCITY COMMERCIAL INTERIORS LTD",
        ),
        expected_rows=2,
        evidence="production jobs CASH SALE - Glen Barratt=1, CASH SALE - SUPERCITY COMMERCIAL INTERIORS LTD=1; shared phone +64274888111",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - VERONICA BARTLETT",
        names=("CASH SALE - VERONICA BARTLETT",),
        expected_rows=2,
        evidence="production jobs CASH SALE - VERONICA BARTLETT=0, CASH SALE - VERONICA BARTLETT=1",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE - VIKING BUILDERS LTD - PHIL",
        names=("CASH SALE - Phil", "CASH SALE - VIKING BUILDERS LTD - PHIL", "Phil"),
        expected_rows=3,
        evidence="production jobs CASH SALE - Phil=1, CASH SALE - VIKING BUILDERS LTD - PHIL=1, Phil=2; shared contact phil; shared phone +642108568997",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE- Penrose motors",
        names=("CASH SALE - STUART WATTS", "CASH SALE- Penrose motors"),
        expected_rows=2,
        evidence="production jobs CASH SALE - STUART WATTS=1, CASH SALE- Penrose motors=1; shared contact stuart watts; shared phone +64278172546",
    ),
    CompanyMergeDecision(
        canonical_name="CASH SALE. Dema Grant",
        names=("CASH - SALE - Dee", "CASH SALE. Dema Grant"),
        expected_rows=2,
        evidence="production jobs CASH - SALE - Dee=1, CASH SALE. Dema Grant=1; shared phone +64279186461",
    ),
    CompanyMergeDecision(
        canonical_name="Cassidy Construction Limited",
        names=("CASH SALE - PETROS PAN", "Cassidy Construction Limited"),
        expected_rows=2,
        evidence="production jobs CASH SALE - PETROS PAN=1, Cassidy Construction Limited=3; shared email domain cassidy.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="CGO Corporate Ltd",
        names=(
            "CASH SALE - Mammoth Brands",
            "CGO (Corporate) Limited",
            "CGO Corporate Ltd",
        ),
        expected_rows=3,
        evidence="production jobs CASH SALE - Mammoth Brands=0, CGO (Corporate) Limited=0, CGO Corporate Ltd=7; shared contact sarah newman; shared email accsupport@mammothbrands.nz; shared email domain mammothbrands.nz; shared email sarah@mammothbrands.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Classic Buildings Limited",
        names=("Classic Buildings Limited", "Solarwind"),
        expected_rows=2,
        evidence="production jobs Classic Buildings Limited=0, Solarwind=0; shared email david@lm3.co.nz; shared email domain lm3.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Co-Mac (PN) Limited",
        names=("Co-Mac (PN) Limited", "comac"),
        expected_rows=2,
        evidence="production jobs Co-Mac (PN) Limited=0, comac=0; shared email domain comac.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="CSP Pacific",
        names=("CSP Pacific", "Martin Swart"),
        expected_rows=2,
        evidence="production jobs CSP Pacific=0, Martin Swart=0; shared email domain csp.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Cushman and Wakefield New Zealand Limited",
        names=(
            "cash sale - ROBERT - CUSHMAN WAKEFIELD",
            "Cushman and Wakefield New Zealand Limited",
            "Rusty Tagicakibau",
        ),
        expected_rows=3,
        evidence="production jobs cash sale - ROBERT - CUSHMAN WAKEFIELD=2, Cushman and Wakefield New Zealand Limited=143, Rusty Tagicakibau=1; shared contact robert; shared email domain cushwake.com; shared email rusty.tagicakibau@cushwake.com; shared phone +64212450109",
    ),
    CompanyMergeDecision(
        canonical_name="Custom Controls Ltd",
        names=("CASH SALE - MARK SEARS", "Custom Controls Ltd"),
        expected_rows=2,
        evidence="production jobs CASH SALE - MARK SEARS=0, Custom Controls Ltd=4; shared contact mark sears; shared email domain customcontrols.co.nz; shared email msears@customcontrols.co.nz; shared phone +6421758031",
    ),
    CompanyMergeDecision(
        canonical_name="D M Dunningham Limited",
        names=("D M Dunningham Limited", "Dion - Dunninghams"),
        expected_rows=2,
        evidence="production jobs D M Dunningham Limited=3, Dion - Dunninghams=0; shared contact dion smit; shared email dion.smit@dunninghams.co.nz; shared email domain dunninghams.co.nz; shared phone +64275556091",
    ),
    CompanyMergeDecision(
        canonical_name="Dave Chown",
        names=("Dave Chown", "David Chown"),
        expected_rows=2,
        evidence="production jobs Dave Chown=0, David Chown=0; shared email tkkid1939@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Davison Construction",
        names=("CASH SALE - LARS DAVISON", "Davison Construction"),
        expected_rows=2,
        evidence="production jobs CASH SALE - LARS DAVISON=2, Davison Construction=5; shared email domain davison.kiwi; shared email lars@davison.kiwi; shared phone +64274052692",
    ),
    CompanyMergeDecision(
        canonical_name="DGE Ltd",
        names=("CASH SALE - Tony Dickson", "DGE Ltd"),
        expected_rows=3,
        evidence="production jobs CASH SALE - Tony Dickson=1, DGE Ltd=0, DGE Ltd=36; shared email domain dge.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Diesel Works",
        names=("Diesel Works", "Paul Harvey"),
        expected_rows=2,
        evidence="production jobs Diesel Works=2, Paul Harvey=0; shared email domain dieselworks.co.nz; shared email paul@dieselworks.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Dormakaba NZ Limited",
        names=("Brian Pates", "Dormakaba NZ Limited"),
        expected_rows=2,
        evidence="production jobs Brian Pates=0, Dormakaba NZ Limited=0; shared email domain dormakaba.com",
    ),
    CompanyMergeDecision(
        canonical_name="Eden park panel and paint",
        names=("CASH SALE#edenpark panel and paint", "Eden park panel and paint"),
        expected_rows=2,
        evidence="production jobs CASH SALE#edenpark panel and paint=1, Eden park panel and paint=0; shared contact ernesto; shared phone +6421629559",
    ),
    CompanyMergeDecision(
        canonical_name="Electrical Importing Company",
        names=("Alan", "CASH SALE - Alan", "Electrical Importing Company"),
        expected_rows=3,
        evidence="production jobs Alan=0, CASH SALE - Alan=0, Electrical Importing Company=5; shared contact alan kelway; shared email domain eic.nz; shared phone +6496342978",
    ),
    CompanyMergeDecision(
        canonical_name="ELS New Zealand Limited",
        names=(
            "CASH SALE - Econic Laundry Solutions",
            "CASH SALE - ELS New Zealand",
            "ELS New Zealand Limited",
        ),
        expected_rows=3,
        evidence="production jobs CASH SALE - Econic Laundry Solutions=1, CASH SALE - ELS New Zealand=1, ELS New Zealand Limited=0; shared contact bob lopesi; shared email domain elsnz.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Evans European Limited",
        names=("Evans European Limited", "Onehunga Car Painters"),
        expected_rows=2,
        evidence="production jobs Evans European Limited=0, Onehunga Car Painters=0; shared email domain evans-euro.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Expac Engineering Ltd (new account)",
        names=(
            "Expac Engineering Ltd (new account)",
            "Expac Engineering Services Old account",
        ),
        expected_rows=2,
        evidence="production jobs Expac Engineering Ltd (new account)=0, Expac Engineering Services Old account=0",
    ),
    CompanyMergeDecision(
        canonical_name="Expol Packaging",
        names=("Chris Agius", "Expol Packaging"),
        expected_rows=2,
        evidence="production jobs Chris Agius=0, Expol Packaging=0; shared email domain expol.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Fab Works Limited",
        names=("CASH SALE - MOHAMMED KHAN", "Fab Works Limited", "Mohammed Khan"),
        expected_rows=3,
        evidence="production jobs CASH SALE - MOHAMMED KHAN=0, Fab Works Limited=1, Mohammed Khan=0; shared phone +64212654413",
    ),
    CompanyMergeDecision(
        canonical_name="Field Services",
        names=("CASH SALE - Field Services", "Field Services"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Field Services=1, Field Services=0; shared email domain fieldservices.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Fieldline NZ Limited",
        names=("Fieldline - old account not in use", "Fieldline NZ Limited"),
        expected_rows=2,
        evidence="production jobs Fieldline - old account not in use=0, Fieldline NZ Limited=0; shared email domain fieldline.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Free Co Flooring",
        names=("CASH SALE - Jason Hu", "Free Co Flooring"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Jason Hu=0, Free Co Flooring=5; shared contact jason hu; shared email domain freecoflooring.co.nz; shared email jason@freecoflooring.co.nz; shared phone +642108588883",
    ),
    CompanyMergeDecision(
        canonical_name="FUZED LTD T/A GAST AUTOMOTIVE",
        names=("CASH SALE - Gaast Automotive", "FUZED LTD T/A GAST AUTOMOTIVE"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Gaast Automotive=1, FUZED LTD T/A GAST AUTOMOTIVE=0; shared email domain gast.co.nz; shared email gareth@gast.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Garry Lawrence Roofing",
        names=("CASH SALE - GARY LAWRENCE", "Garry Lawrence Roofing"),
        expected_rows=2,
        evidence="production jobs CASH SALE - GARY LAWRENCE=1, Garry Lawrence Roofing=1; shared contact gary lawrence; shared phone +6421969601",
    ),
    CompanyMergeDecision(
        canonical_name="Gilmours Mt Roskill",
        names=("Gilmours Mt Roskill", "Greg Martin"),
        expected_rows=2,
        evidence="production jobs Gilmours Mt Roskill=0, Greg Martin=0; shared email domain gilmours.co.nz; shared email gregory.martin@gilmours.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Gordon & Ryan (2022) Ltd",
        names=("CASH SALE - SALIM SHAIKH", "Gordon & Ryan (2022) Ltd"),
        expected_rows=2,
        evidence="production jobs CASH SALE - SALIM SHAIKH=2, Gordon & Ryan (2022) Ltd=0; shared email domain gordonandryan.co.nz; shared email salim@gordonandryan.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Grace International",
        names=("Grace International", "Vidak Druskovich"),
        expected_rows=2,
        evidence="production jobs Grace International=0, Vidak Druskovich=1; shared email vidakdruskovich@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Graphic Packaging International NZ Ltd",
        names=(
            "CASH SALE - Graphic Packaging",
            "Graphic Packaging International NZ Ltd",
        ),
        expected_rows=2,
        evidence="production jobs CASH SALE - Graphic Packaging=1, Graphic Packaging International NZ Ltd=0; shared email domain graphicpkg.com",
    ),
    CompanyMergeDecision(
        canonical_name="Groundtest Equipment",
        names=("Groundtest Equipment", "Seite-Last Engineering"),
        expected_rows=2,
        evidence="production jobs Groundtest Equipment=1, Seite-Last Engineering=1; shared email domain groundtest.co.nz; shared email richard@groundtest.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Gus Kanji",
        names=("CASH SALE - GUS KANJI", "Gus Kanji"),
        expected_rows=2,
        evidence="production jobs CASH SALE - GUS KANJI=4, Gus Kanji=5; shared contact gus kanji; shared email domain icloud.com; shared email guskanji@icloud.com; shared phone +64274500727",
    ),
    CompanyMergeDecision(
        canonical_name="Health Pak Limited",
        names=("Aaron Wilson", "Health Pak Limited"),
        expected_rows=2,
        evidence="production jobs Aaron Wilson=1, Health Pak Limited=1; shared phone +64210640540",
    ),
    CompanyMergeDecision(
        canonical_name="Hercules Crane and Rigging",
        names=("Hercules Crane and Rigging", "Hercules Cranes and Rigging"),
        expected_rows=2,
        evidence="production jobs Hercules Crane and Rigging=2, Hercules Cranes and Rigging=0; shared phone +64272398572",
    ),
    CompanyMergeDecision(
        canonical_name="High Mark Foods",
        names=("CASH SALE - MICHAEL CHEE", "High Mark Foods"),
        expected_rows=2,
        evidence="production jobs CASH SALE - MICHAEL CHEE=2, High Mark Foods=3; shared contact michael chee; shared phone +6421673290",
    ),
    CompanyMergeDecision(
        canonical_name="HTS Group Ltd",
        names=("Ed Macdonald", "HTS Group Ltd", "HTS Group LTD - Ed Macdonald"),
        expected_rows=3,
        evidence="production jobs Ed Macdonald=0, HTS Group Ltd=0, HTS Group LTD - Ed Macdonald=3; shared contact ed macdonald; shared email domain htsgroup.co.nz; shared email emacdonald@htsgroup.co.nz; shared phone +64272412956",
    ),
    CompanyMergeDecision(
        canonical_name="HV Power Measurements and Protection Ltd",
        names=("HV Power Measurements and Protection Ltd", "Wim Van Den Berg"),
        expected_rows=2,
        evidence="production jobs HV Power Measurements and Protection Ltd=15, Wim Van Den Berg=0; shared email domain hvpowerautomation.com",
    ),
    CompanyMergeDecision(
        canonical_name="Hynds Pipe Systems Limited",
        names=("CASH - SALE - HYNDS - Kayleen Currie", "Hynds Pipe Systems Limited"),
        expected_rows=2,
        evidence="production jobs CASH - SALE - HYNDS - Kayleen Currie=2, Hynds Pipe Systems Limited=18; shared email domain hynds.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Insurance Resources - PSC Connect NZ Ltd",
        names=("Insurance Resources - PSC Connect NZ Ltd", "rick"),
        expected_rows=2,
        evidence="production jobs Insurance Resources - PSC Connect NZ Ltd=0, rick=0; shared email domain insuranceresources.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="INTERIOR DB LIMITED",
        names=("CASH SALE - CHRISTOPHER WATT", "INTERIOR DB LIMITED"),
        expected_rows=2,
        evidence="production jobs CASH SALE - CHRISTOPHER WATT=0, INTERIOR DB LIMITED=3; shared email christopher@interiordb.co.nz; shared email domain interiordb.co.nz; shared phone +64275382037",
    ),
    CompanyMergeDecision(
        canonical_name="IPL Maintenance",
        names=("CASH SALE - IPL maintenance", "IPL Maintenance"),
        expected_rows=2,
        evidence="production jobs CASH SALE - IPL maintenance=0, IPL Maintenance=7; shared contact dave allan; shared email domain yahoo.com; shared email iplmaintenance@yahoo.com; shared phone +64274884866",
    ),
    CompanyMergeDecision(
        canonical_name="Irving",
        names=("CASH SALE - IRVING", "CASH SALE -Irving", "Irving"),
        expected_rows=3,
        evidence="production jobs CASH SALE - IRVING=2, CASH SALE -Irving=1, Irving=0; shared contact irving; shared email herbpatch20@gmail.com; shared phone +6421378335",
    ),
    CompanyMergeDecision(
        canonical_name="Jack Lum and Co Limited",
        names=(
            "CASH SALE - Jack Lum and Co.",
            "CASH SALE - Mike Lum",
            "Jack Lum and Co Limited",
        ),
        expected_rows=3,
        evidence="production jobs CASH SALE - Jack Lum and Co.=1, CASH SALE - Mike Lum=0, Jack Lum and Co Limited=0; shared contact mike lum; shared email domain email.com; shared email mikelum@email.com; shared phone +6421301188",
    ),
    CompanyMergeDecision(
        canonical_name="Jenny Stevens",
        names=("CASH SALE - Jenny stevens", "Jenny Stevens"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Jenny stevens=1, Jenny Stevens=1; shared contact jenny stevens; shared email jennifersteven@gmail.com; shared phone +64210583499",
    ),
    CompanyMergeDecision(
        canonical_name="Jerry Friar",
        names=("CASH SALE - Jerry Friar", "Jerry Friar"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Jerry Friar=2, Jerry Friar=1; shared contact jerry friar; shared phone +6421563894",
    ),
    CompanyMergeDecision(
        canonical_name="JJ Wafer Biscuits Limited",
        names=("arshay@wafers.co.nz", "JJ Wafer Biscuits Limited"),
        expected_rows=2,
        evidence="production jobs arshay@wafers.co.nz=0, JJ Wafer Biscuits Limited=0; shared email domain wafers.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Jocelyn Croad",
        names=("CASH - SALE - Jocelyn Croad", "Jocelyn Croad"),
        expected_rows=2,
        evidence="production jobs CASH - SALE - Jocelyn Croad=1, Jocelyn Croad=0",
    ),
    CompanyMergeDecision(
        canonical_name="John",
        names=("CASH SALE - JOHN", "John"),
        expected_rows=2,
        evidence="production jobs CASH SALE - JOHN=0, John=0",
    ),
    CompanyMergeDecision(
        canonical_name="Joseph Haydock",
        names=("Joesph Haydock", "Joseph Haydock"),
        expected_rows=2,
        evidence="production jobs Joesph Haydock=1, Joseph Haydock=1; shared phone +642040142511",
    ),
    CompanyMergeDecision(
        canonical_name="K & V Properties Ltd",
        names=("K & V Properties Ltd", "Vladimir"),
        expected_rows=2,
        evidence="production jobs K & V Properties Ltd=0, Vladimir=0; shared email brico191441@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Keith Adams Plumbing",
        names=("Cougar Trust", "Keith Adams Plumbing"),
        expected_rows=2,
        evidence="production jobs Cougar Trust=0, Keith Adams Plumbing=0; shared email plumber.keith@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="KTS Roofing and Spouting",
        names=("CASH SALE - KIWI TRADE SERVICES", "KTS Roofing and Spouting"),
        expected_rows=2,
        evidence="production jobs CASH SALE - KIWI TRADE SERVICES=1, KTS Roofing and Spouting=0; shared email domain kts.kiwi",
    ),
    CompanyMergeDecision(
        canonical_name="Lakeland Consulting",
        names=("Corrin Lakeland", "Lakeland Consulting"),
        expected_rows=2,
        evidence="production jobs Corrin Lakeland=2, Lakeland Consulting=0; shared email lakeland@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Laurie Miller",
        names=("CASH SALE - Laurie Miller", "Laurie Miller"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Laurie Miller=1, Laurie Miller=0",
    ),
    CompanyMergeDecision(
        canonical_name="Leap Innovation NZ",
        names=("Ben King", "Leap Innovation NZ"),
        expected_rows=2,
        evidence="production jobs Ben King=1, Leap Innovation NZ=1; shared email ben@leapinnovation.nz; shared email domain leapinnovation.nz; shared phone +64275259552",
    ),
    CompanyMergeDecision(
        canonical_name="Lindsay Building Services",
        names=(
            "CASH SALE - Lindsay Building Services",
            "Lindsay Building Services",
            "Mike Lindsay",
            "tony m",
        ),
        expected_rows=4,
        evidence="production jobs CASH SALE - Lindsay Building Services=2, Lindsay Building Services=1, Mike Lindsay=0, tony m=1; shared email domain lindsaybuildingservices.co.nz; shared email mike@lindsaybuildingservices.co.nz; shared phone +64212216699",
    ),
    CompanyMergeDecision(
        canonical_name="LT McGuinness Auckland Limited",
        names=(
            "CASH SALE - LT MCGUINESS",
            "CASH SALE - LT MCGUINNESS",
            "LT McGuinness Auckland Limited",
        ),
        expected_rows=3,
        evidence="production jobs CASH SALE - LT MCGUINESS=0, CASH SALE - LT MCGUINNESS=0, LT McGuinness Auckland Limited=5; shared email byronc@mcguinness.co.nz; shared email domain mcguinness.co.nz; shared phone +6421527295",
    ),
    CompanyMergeDecision(
        canonical_name="MAG Assembly",
        names=("CASH SALE - Philip Officer", "MAG Assembly"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Philip Officer=1, MAG Assembly=11; shared email domain magassembly.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Maraia",
        names=("CASH SALE - Maraia", "Maraia"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Maraia=0, Maraia=0; shared phone +64210341340; shared phone +64341340",
    ),
    CompanyMergeDecision(
        canonical_name="MATERIAL HANDLING SOLUTIONS",
        names=("Handro", "MATERIAL HANDLING SOLUTIONS"),
        expected_rows=2,
        evidence="production jobs Handro=1, MATERIAL HANDLING SOLUTIONS=1; shared phone +64212892852",
    ),
    CompanyMergeDecision(
        canonical_name="MC ALPINE HUSSMANN",
        names=("CASH SALE - MCALPINE HUSSMANN", "MC ALPINE HUSSMANN"),
        expected_rows=2,
        evidence="production jobs CASH SALE - MCALPINE HUSSMANN=0, MC ALPINE HUSSMANN=5; shared email domain hussmann.com; shared email tim.moore@hussmann.com; shared phone +64272240844",
    ),
    CompanyMergeDecision(
        canonical_name="McConnell Dowell Constructors Limited",
        names=("CASH SALE - MIKE BONNETTE", "McConnell Dowell Constructors Limited"),
        expected_rows=2,
        evidence="production jobs CASH SALE - MIKE BONNETTE=1, McConnell Dowell Constructors Limited=0; shared email domain mcdgroup.com",
    ),
    CompanyMergeDecision(
        canonical_name="McDonald Vague Limited",
        names=("CASH SALE - McDonald Vague", "McDonald Vague Limited"),
        expected_rows=2,
        evidence="production jobs CASH SALE - McDonald Vague=1, McDonald Vague Limited=0",
    ),
    CompanyMergeDecision(
        canonical_name="Mehmet Doker",
        names=("CASH SALE - MEHMET DOKER", "Mehmet Doker"),
        expected_rows=2,
        evidence="production jobs CASH SALE - MEHMET DOKER=2, Mehmet Doker=0; shared email mehmetdoker@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Michael Mackinven",
        names=("CASH SALE - Michael Mackinven", "Michael Mackinven"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Michael Mackinven=4, Michael Mackinven=0; shared email mackinven@hotmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Mike (Michael) Loomb",
        names=("CASH SALE - Mike Loomb", "Mike (Michael) Loomb"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Mike Loomb=2, Mike (Michael) Loomb=1; shared email michaelloomb@hotmail.com; shared phone +64211951166",
    ),
    CompanyMergeDecision(
        canonical_name="Miles Motor Group",
        names=("Miles Motor Group", "Paul Curin"),
        expected_rows=2,
        evidence="production jobs Miles Motor Group=0, Paul Curin=0; shared email domain miles.co.nz; shared email pcurin@miles.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Motul New Zealand",
        names=("CASH SALE - CHRIS", "Chris", "Motul New Zealand"),
        expected_rows=3,
        evidence="production jobs CASH SALE - CHRIS=2, Chris=0, Motul New Zealand=0; shared email domain motul.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="NEP Broadcast Services New Zealand Limited",
        names=("CASH SALE - Nick Haines", "NEP Broadcast Services New Zealand Limited"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Nick Haines=0, NEP Broadcast Services New Zealand Limited=4; shared contact nick haines",
    ),
    CompanyMergeDecision(
        canonical_name="NEW ZEALAND STARCH",
        names=("NEW ZEALAND STARCH", "NZ STARCH"),
        expected_rows=2,
        evidence="production jobs NEW ZEALAND STARCH=1, NZ STARCH=1; shared contact brett johnson; shared email brett.johnson@nzstarch.co.nz; shared email domain nzstarch.co.nz; shared phone +64273005151",
    ),
    CompanyMergeDecision(
        canonical_name="Nick Hansen",
        names=("CASH SALE Nick Hansen", "Nick Hansen"),
        expected_rows=2,
        evidence="production jobs CASH SALE Nick Hansen=3, Nick Hansen=1; shared contact nick hansen; shared email domain hotmail.co.nz; shared email nickhprogresse@hotmail.co.nz; shared phone +64272968753",
    ),
    CompanyMergeDecision(
        canonical_name="Nordson Australia Pty Limited",
        names=("Nordson Australia Pty Limited", "Rodney Lambert"),
        expected_rows=2,
        evidence="production jobs Nordson Australia Pty Limited=3, Rodney Lambert=0; shared email domain nordson.com; shared email rodney.lambert@nordson.com",
    ),
    CompanyMergeDecision(
        canonical_name="Northland Roofs NZ",
        names=("CASH SALE - Northland Roofs NZ", "Northland Roofs NZ"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Northland Roofs NZ=17, Northland Roofs NZ=11; shared contact ace punia; shared email ace.p@northlandroofs.com; shared email domain northlandroofs.com; shared email parisa.m@northlandroofs.com",
    ),
    CompanyMergeDecision(
        canonical_name="NZ Crane Hire Limited",
        names=("Danny - NZ Crane", "NZ Crane Hire Limited", "Scott Sandford"),
        expected_rows=3,
        evidence="production jobs Danny - NZ Crane=1, NZ Crane Hire Limited=14, Scott Sandford=0; shared contact danny newberry; shared email domain cranehire.co.nz; shared phone +6421747065",
    ),
    CompanyMergeDecision(
        canonical_name="Oji Fibre Solutions - Penrose Mill",
        names=("Mark Bendikson", "Oji Fibre Solutions - Penrose Mill"),
        expected_rows=2,
        evidence="production jobs Mark Bendikson=0, Oji Fibre Solutions - Penrose Mill=0; shared email domain ojifs.com",
    ),
    CompanyMergeDecision(
        canonical_name="Omaha Beach Golf Club",
        names=("Geoff Smith 0274985382", "Omaha Beach Golf Club"),
        expected_rows=2,
        evidence="production jobs Geoff Smith 0274985382=1, Omaha Beach Golf Club=0; shared email geoffsmith08@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Onehunga Auto Electric Ltd",
        names=("CASH SALE-Rob Wedding", "Onehunga Auto Electric Ltd"),
        expected_rows=2,
        evidence="production jobs CASH SALE-Rob Wedding=2, Onehunga Auto Electric Ltd=0; shared email onehungaae@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Onsite Team",
        names=("Onsite Engineering Ltd", "Onsite Team"),
        expected_rows=2,
        evidence="production jobs Onsite Engineering Ltd=0, Onsite Team=21; shared contact gary mcnabb; shared email domain onsiteteam.co.nz; shared email gary@onsiteteam.co.nz; shared phone +6421848568",
    ),
    CompanyMergeDecision(
        canonical_name="Owen Dwyer",
        names=("CASH SALE - Owen Dwyer", "Owen Dwyer"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Owen Dwyer=2, Owen Dwyer=0",
    ),
    CompanyMergeDecision(
        canonical_name="pacific bakery Mangere",
        names=(
            "CASH SALE-pacific bakery Mangere",
            "Mangere town bakery",
            "pacific bakery Mangere",
        ),
        expected_rows=3,
        evidence="production jobs CASH SALE-pacific bakery Mangere=2, Mangere town bakery=1, pacific bakery Mangere=3; shared contact andrew winston; shared email domain yahoo.com; shared email pacbakery@yahoo.com; shared phone +64220308090",
    ),
    CompanyMergeDecision(
        canonical_name="Paul De Blois",
        names=("CASH SALE - PAUL DE BLOIS", "Paul De Blois"),
        expected_rows=2,
        evidence="production jobs CASH SALE - PAUL DE BLOIS=0, Paul De Blois=1; shared email domain hotmail.co.nz; shared email rsmk1paul@hotmail.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="PB Traffic",
        names=("PB Traffic", "PB traffic solutions"),
        expected_rows=2,
        evidence="production jobs PB Traffic=51, PB traffic solutions=0; shared contact akshay; shared contact emilio rueda; shared phone +64211462453; shared phone +64272097842",
    ),
    CompanyMergeDecision(
        canonical_name="pcs painting",
        names=("CASH SALE - PCS PAINTING", "pcs painting"),
        expected_rows=2,
        evidence="production jobs CASH SALE - PCS PAINTING=2, pcs painting=1; shared email pcspainting@xtra.co.nz; shared phone +6421723969",
    ),
    CompanyMergeDecision(
        canonical_name="Penrose Paper Engineering",
        names=(
            "CASH SALE - MATT GREEN",
            "CASH SALE MATT GREEN",
            "CASH SALE-Kidantics",
            "Matt Green",
            "Penrose Paper Engineering",
        ),
        expected_rows=5,
        evidence="production jobs CASH SALE - MATT GREEN=1, CASH SALE MATT GREEN=0, CASH SALE-Kidantics=1, Matt Green=1, Penrose Paper Engineering=2; shared contact matt green; shared email domain kidantics.co.nz; shared email matt@kidantics.co.nz; shared email penrosepaper@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Performance Cleaners",
        names=("Performance Cleaners", "Peter Barron"),
        expected_rows=2,
        evidence="production jobs Performance Cleaners=0, Peter Barron=0; shared email pcebarron@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Pete Pederson",
        names=("CASH SALE - Pete Pederson", "CASH SALE#Pete Pederson", "Pete Pederson"),
        expected_rows=3,
        evidence="production jobs CASH SALE - Pete Pederson=1, CASH SALE#Pete Pederson=1, Pete Pederson=0; shared phone +64274300224",
    ),
    CompanyMergeDecision(
        canonical_name="Peter Champion",
        names=("Peter Champion", "Peter Chapman"),
        expected_rows=2,
        evidence="production jobs Peter Champion=0, Peter Chapman=0; shared email ezycall@xtra.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Playhouse Theatre",
        names=("Playhouse Theatre", "Tony Morrow"),
        expected_rows=2,
        evidence="production jobs Playhouse Theatre=0, Tony Morrow=0; shared email mdoherty.pjones@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Point Maintenance",
        names=("cash sale phillip", "Phillip Whitham", "Point Maintenance"),
        expected_rows=3,
        evidence="production jobs cash sale phillip=1, Phillip Whitham=1, Point Maintenance=4; shared contact philip; shared email phil.point@outlook.com; shared phone +64277033500",
    ),
    CompanyMergeDecision(
        canonical_name="PPG Industrial Coatings NZ",
        names=("BDM - Commercial Transport", "PPG Industrial Coatings NZ"),
        expected_rows=2,
        evidence="production jobs BDM - Commercial Transport=0, PPG Industrial Coatings NZ=10; shared email domain ppg.com",
    ),
    CompanyMergeDecision(
        canonical_name="Proclimb",
        names=("CASH SALE - SIMON ROSE", "Proclimb"),
        expected_rows=2,
        evidence="production jobs CASH SALE - SIMON ROSE=1, Proclimb=1; shared contact simon rose; shared email domain proclimb.co.nz; shared email simon.rose@proclimb.co.nz; shared phone +64276642307",
    ),
    CompanyMergeDecision(
        canonical_name="QC Projects",
        names=("John Williams", "John Williams -", "QC Projects"),
        expected_rows=3,
        evidence="production jobs John Williams=0, John Williams -=0, QC Projects=0; shared email domain qcprojects.co.nz; shared email john@qcprojects.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Rauland NZ Limited",
        names=("CASH SALE - Rauland", "Rauland NZ Limited"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Rauland=3, Rauland NZ Limited=1; shared contact alvin bonita; shared email alvinbonita@rauland.co.nz; shared email domain rauland.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Reece Taituha",
        names=("CASH SALE - REECE TAITUHA", "Reece Taituha"),
        expected_rows=2,
        evidence="production jobs CASH SALE - REECE TAITUHA=1, Reece Taituha=0; shared email reecetaituha@live.com",
    ),
    CompanyMergeDecision(
        canonical_name="REMUERA PROPERTY SERVICES",
        names=(
            "CASH SALE - REMUERA PROPERTY SERVICES",
            "REMUERA PROPERTY SERVICES",
            "Terry Brailford",
        ),
        expected_rows=3,
        evidence="production jobs CASH SALE - REMUERA PROPERTY SERVICES=0, REMUERA PROPERTY SERVICES=2, Terry Brailford=1; shared email rpsltd@xtra.co.nz; shared phone +64274958816",
    ),
    CompanyMergeDecision(
        canonical_name="Rexmark Developments",
        names=("Rex Sellars", "Rexmark Developments"),
        expected_rows=2,
        evidence="production jobs Rex Sellars=0, Rexmark Developments=0; shared email domain sellar.nz; shared email rex@sellar.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Ripout NZ Ltd",
        names=("CASH SALE - Mark Homan", "Ripout NZ Ltd"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Mark Homan=0, Ripout NZ Ltd=5; shared contact mark homan; shared phone +6421744827",
    ),
    CompanyMergeDecision(
        canonical_name="Robert Grant",
        names=("Robbie Grant", "Robert Grant"),
        expected_rows=2,
        evidence="production jobs Robbie Grant=1, Robert Grant=1; shared phone +6421502802",
    ),
    CompanyMergeDecision(
        canonical_name="Rocket Lab NZ Ltd",
        names=("CASH SALE - KRISH RUPAN", "Rocket Lab NZ Ltd"),
        expected_rows=2,
        evidence="production jobs CASH SALE - KRISH RUPAN=1, Rocket Lab NZ Ltd=1; shared email domain rocketlab.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Ron - Landform",
        names=("Ron - Landform", "Ron Grosse"),
        expected_rows=2,
        evidence="production jobs Ron - Landform=0, Ron Grosse=0; shared email landformnz@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="ROOTS R US Ltd - Balli",
        names=("CASH SALE - BALLI (ROOTS R US LTD)", "ROOTS R US Ltd - Balli"),
        expected_rows=2,
        evidence="production jobs CASH SALE - BALLI (ROOTS R US LTD)=2, ROOTS R US Ltd - Balli=1; shared phone +64204336699",
    ),
    CompanyMergeDecision(
        canonical_name="SD Aluminium LTD",
        names=("SD Aluminium", "SD Aluminium LTD"),
        expected_rows=2,
        evidence="production jobs SD Aluminium=0, SD Aluminium LTD=0",
    ),
    CompanyMergeDecision(
        canonical_name="Secair - Compressed Air Solutions",
        names=("CASH - SALE - Earl Warne", "Secair - Compressed Air Solutions"),
        expected_rows=2,
        evidence="production jobs CASH - SALE - Earl Warne=1, Secair - Compressed Air Solutions=0; shared email domain secair.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Signbiz",
        names=("CASH - SALE - SIGNBIZ", "Signbiz"),
        expected_rows=2,
        evidence="production jobs CASH - SALE - SIGNBIZ=1, Signbiz=0; shared email domain signbiz.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Silent Generator Company",
        names=("Aaron Thorpe", "Silent Generator Company"),
        expected_rows=2,
        evidence="production jobs Aaron Thorpe=0, Silent Generator Company=1; shared email silentgeneratorcompany@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Simon",
        names=("CASH SALE - Simon", "Simon"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Simon=0, Simon=1",
    ),
    CompanyMergeDecision(
        canonical_name="SMG Ltd",
        names=("SMG", "SMG Ltd"),
        expected_rows=2,
        evidence="production jobs SMG=0, SMG Ltd=0",
    ),
    CompanyMergeDecision(
        canonical_name="Snowdon Consulting",
        names=("Snowden", "Snowdon Consulting"),
        expected_rows=2,
        evidence="production jobs Snowden=1, Snowdon Consulting=12; shared contact charlie thomlinson; shared phone +642108658458",
    ),
    CompanyMergeDecision(
        canonical_name="St David's Church",
        names=("David Brown", "St David's Church"),
        expected_rows=2,
        evidence="production jobs David Brown=0, St David's Church=0; shared email david-empireroad@hotmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Stainless Products Limited",
        names=("Blair Tribe", "Stainless Products Limited"),
        expected_rows=2,
        evidence="production jobs Blair Tribe=0, Stainless Products Limited=0; shared email domain stainlessproducts.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Steam Brewing Limited",
        names=("CASH SALE - Steam Brewing Steve Kermode", "Steam Brewing Limited"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Steam Brewing Steve Kermode=1, Steam Brewing Limited=0; shared email domain steambrewing.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Stebbing Recording Centre Ltd",
        names=("Robert Stebbing", "Stebbing Recording Centre Ltd"),
        expected_rows=2,
        evidence="production jobs Robert Stebbing=0, Stebbing Recording Centre Ltd=0; shared email domain stebbing.co.nz; shared email robert@stebbing.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Steel Windows and Doors",
        names=("Steel Profiles", "Steel Windows and Doors"),
        expected_rows=2,
        evidence="production jobs Steel Profiles=0, Steel Windows and Doors=0; shared email domain steelwindowsanddoors.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Stephen (Steve) Carr",
        names=(
            "CASH SALE - STEPHEN CARR",
            "CASH SALE - Steve Carr",
            "Stephen (Steve) Carr",
        ),
        expected_rows=3,
        evidence="production jobs CASH SALE - STEPHEN CARR=1, CASH SALE - Steve Carr=2, Stephen (Steve) Carr=2; shared contact stephen carr; shared email daimlersteve@gmail.com; shared phone +64275120443",
    ),
    CompanyMergeDecision(
        canonical_name="Steve Kirby",
        names=("CASH SALE - Steve Kirby", "Steve Kirby"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Steve Kirby=0, Steve Kirby=2; shared email kirby.nz@gmail.com; shared phone +6421354532",
    ),
    CompanyMergeDecision(
        canonical_name="Straightline Builders",
        names=("Bryson Rangi", "Straightline Builders"),
        expected_rows=2,
        evidence="production jobs Bryson Rangi=0, Straightline Builders=0; shared email bryson@slb.co.nz; shared email domain slb.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Testing client name 3",
        names=("Testing client name 3", "Testing Corrin 3"),
        expected_rows=2,
        evidence="production jobs Testing client name 3=0, Testing Corrin 3=0; shared email lakeland+testing3@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Textile Products 1971 Limited",
        names=(
            "CASH SALE - Matt O'Connor",
            "Kevin Sanderson",
            "Textile Products 1971 Limited",
        ),
        expected_rows=3,
        evidence="production jobs CASH SALE - Matt O'Connor=1, Kevin Sanderson=0, Textile Products 1971 Limited=6; shared email domain textile.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="The Learning Wave",
        names=("The Learning Wave", "Yellowjelly Limited"),
        expected_rows=2,
        evidence="production jobs The Learning Wave=0, Yellowjelly Limited=0; shared email domain thelearningwave.com; shared email richardm@thelearningwave.com",
    ),
    CompanyMergeDecision(
        canonical_name="Tim Cooper",
        names=("CASH SALE - TIM COOPER", "Tim Cooper"),
        expected_rows=2,
        evidence="production jobs CASH SALE - TIM COOPER=1, Tim Cooper=0",
    ),
    CompanyMergeDecision(
        canonical_name="Timeworx",
        names=(
            "CASH SALE - PAUL O'BRIEN",
            "Da Vinci Trust",
            "Paul O'Brien",
            "Timeworx",
        ),
        expected_rows=4,
        evidence="production jobs CASH SALE - PAUL O'BRIEN=3, Da Vinci Trust=0, Paul O'Brien=0, Timeworx=2; shared contact paul o brien; shared email domain timeworx.co.nz; shared email paul@timeworx.co.nz; shared email paulobrien575@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="TNJ and S A Morris",
        names=("GLEN MARINE TRUST", "TNJ and S A Morris"),
        expected_rows=2,
        evidence="production jobs GLEN MARINE TRUST=0, TNJ and S A Morris=0; shared email tomshirl10@gmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="tom c",
        names=("thomas", "tom .c", "tom c"),
        expected_rows=3,
        evidence="production jobs thomas=1, tom .c=0, tom c=0; shared phone +64220446045",
    ),
    CompanyMergeDecision(
        canonical_name="Total Home Renovation",
        names=("Ross Collins", "Total Home Renovation"),
        expected_rows=2,
        evidence="production jobs Ross Collins=0, Total Home Renovation=0; shared email domain thr.nz; shared email ross@thr.nz",
    ),
    CompanyMergeDecision(
        canonical_name="TR Group Ltd",
        names=("Sam Davies", "TR Group Ltd"),
        expected_rows=2,
        evidence="production jobs Sam Davies=0, TR Group Ltd=0; shared email domain trgroup.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Twist Prop 1 Limited",
        names=("Mark Boucher 021922804", "Twist Prop 1 Limited"),
        expected_rows=2,
        evidence="production jobs Mark Boucher 021922804=0, Twist Prop 1 Limited=0; shared email boucher@actrix.co.nz; shared email domain actrix.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Ultralon Foam International",
        names=("Peter Manhire", "Ultralon Foam International"),
        expected_rows=2,
        evidence="production jobs Peter Manhire=1, Ultralon Foam International=1; shared contact peter manhire; shared phone +6421642273",
    ),
    CompanyMergeDecision(
        canonical_name="Vat Cleaning Services",
        names=("Kevin Gardiner", "Vat Cleaning Services"),
        expected_rows=2,
        evidence="production jobs Kevin Gardiner=0, Vat Cleaning Services=0; shared email kevin.vatclean@xtra.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Vern Patel",
        names=("CASH SALE - Vern Patel", "Vern Patel"),
        expected_rows=2,
        evidence="production jobs CASH SALE - Vern Patel=1, Vern Patel=0; shared email vern.patel@hotmail.com",
    ),
    CompanyMergeDecision(
        canonical_name="Vulcan Steel Limited",
        names=(
            "Vulcan Steel Limited",
            "Vulcan Ullrich Aluminium - do not use 2763789 onehunga",
        ),
        expected_rows=2,
        evidence="production jobs Vulcan Steel Limited=0, Vulcan Ullrich Aluminium - do not use 2763789 onehunga=0; shared email accounts.nzl@vulcan.co; shared email domain vulcan.co",
    ),
    CompanyMergeDecision(
        canonical_name="Wakefield Metals",
        names=("CASH SALE - WAKEFIELDS METALS", "Wakefield Metals"),
        expected_rows=2,
        evidence="production jobs CASH SALE - WAKEFIELDS METALS=0, Wakefield Metals=2; shared email domain wmetals.co.nz; shared email matthew.macdonald@wmetals.co.nz; shared phone +64212426732",
    ),
    CompanyMergeDecision(
        canonical_name="Wallace Investments Ltd",
        names=("Cedric/Wallace Investments", "Wallace Investments Ltd"),
        expected_rows=2,
        evidence="production jobs Cedric/Wallace Investments=0, Wallace Investments Ltd=0; shared email domain wil.stevedores.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Walter and Wild Limited",
        names=("Nick Pretscherer", "Nicklaus Pretscherer", "Walter and Wild Limited"),
        expected_rows=3,
        evidence="production jobs Nick Pretscherer=0, Nicklaus Pretscherer=0, Walter and Wild Limited=3; shared email domain walterandwild.com; shared email nicklausp@walterandwild.com",
    ),
    CompanyMergeDecision(
        canonical_name="Watercone ltd (Neville)",
        names=("The water cone", "Watercone ltd (Neville)"),
        expected_rows=2,
        evidence="production jobs The water cone=1, Watercone ltd (Neville)=2; shared contact neville; shared phone +6421922819",
    ),
    CompanyMergeDecision(
        canonical_name="Wolfgang Schenk",
        names=("CASH SALE - WOLFGANG", "Wolfgang Schenk"),
        expected_rows=2,
        evidence="production jobs CASH SALE - WOLFGANG=2, Wolfgang Schenk=1; shared contact wolfgang; shared phone +64211253754",
    ),
    CompanyMergeDecision(
        canonical_name="Wright Panel and Paint",
        names=("CASH SALE - WRIGHT PANEL AND PAINT", "Wright Panel and Paint"),
        expected_rows=2,
        evidence="production jobs CASH SALE - WRIGHT PANEL AND PAINT=1, Wright Panel and Paint=0; shared email wcpp@xtra.co.nz",
    ),
    CompanyMergeDecision(
        canonical_name="Xero (NZ) Limited",
        names=("Xero (NZ) Limited", "Xero NZ"),
        expected_rows=2,
        evidence="production jobs Xero (NZ) Limited=0, Xero NZ=0",
    ),
    CompanyMergeDecision(
        canonical_name="Yoshiki Fujimoto",
        names=("CASH SALE - YOSHIKI FUJIMOTO", "Yoshiki Fujimoto"),
        expected_rows=2,
        evidence="production jobs CASH SALE - YOSHIKI FUJIMOTO=0, Yoshiki Fujimoto=2",
    ),
)

REVIEWED_PERSON_MERGES: tuple[PersonMergeDecision, ...] = (
    PersonMergeDecision(
        canonical=PersonSelector("Aaron Williams", "aaron.w@dge.nz", "DGE Ltd"),
        members=(
            PersonSelector("Aaron Williams", None, "Auckland Airport Limited"),
            PersonSelector("Aaron Williams", "aaron.w@dge.nz", "DGE Ltd"),
            PersonSelector("Aarron Williams", None, "DGE Ltd"),
        ),
        expected_people=3,
        evidence="production jobs Aaron Williams=1, Aaron Williams=24, Aarron Williams=1; shared phone +64274783139",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "ACE PUNIA", "ace.p@northlandroofs.com", "CASH SALE - Northland Roofs NZ"
        ),
        members=(
            PersonSelector(
                "ACE PUNIA", "ace.p@northlandroofs.com", "Northland Roofs NZ"
            ),
            PersonSelector(
                "ACE PUNIA",
                "ace.p@northlandroofs.com",
                "CASH SALE - Northland Roofs NZ",
            ),
        ),
        expected_people=2,
        evidence="production jobs ACE PUNIA=1, ACE PUNIA=7; shared email ace.p@northlandroofs.com; shared phone +642108225902",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Akshay", None, "PB Traffic"),
        members=(
            PersonSelector("Akshay", None, "PB Traffic"),
            PersonSelector("Akshay", None, "PB traffic solutions"),
            PersonSelector("AKSHAY GUPTE", "akshay@pbtraffic.co.nz", "PB Traffic"),
        ),
        expected_people=3,
        evidence="production jobs Akshay=22, Akshay=1, AKSHAY GUPTE=17; shared phone +64211462453",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Alan Kelway", None, "Electrical Importing Company"),
        members=(
            PersonSelector("Alan Kelway", None, "Electrical Importing Company"),
            PersonSelector("Alan Kelway", "alan@eicnz.com", "CASH SALE - Alan"),
        ),
        expected_people=2,
        evidence="production jobs Alan Kelway=4, Alan Kelway=0",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Alvin Bonita", "AlvinBonita@rauland.co.nz", "CASH SALE - Rauland"
        ),
        members=(
            PersonSelector(
                "Alvin Bonita", "AlvinBonita@rauland.co.nz", "CASH SALE - Rauland"
            ),
            PersonSelector(
                "Alvin Bonita", "AlvinBonita@rauland.co.nz", "Rauland NZ Limited"
            ),
        ),
        expected_people=2,
        evidence="production jobs Alvin Bonita=3, Alvin Bonita=0; shared email alvinbonita@rauland.co.nz",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Andrew Winston", "pacbakery@yahoo.com", "pacific bakery Mangere"
        ),
        members=(
            PersonSelector("Andrew", None, "Mangere town bakery"),
            PersonSelector(
                "Andrew Winston", "pacbakery@yahoo.com", "pacific bakery Mangere"
            ),
            PersonSelector(
                "Andrew Winston",
                "pacbakery@yahoo.com",
                "CASH SALE-pacific bakery Mangere",
            ),
        ),
        expected_people=3,
        evidence="production jobs Andrew=1, Andrew Winston=3, Andrew Winston=1; shared email pacbakery@yahoo.com; shared phone +64220308090",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Angela", "Angela.Malden@hynds.co.nz", "Hynds Pipe Systems Limited"
        ),
        members=(
            PersonSelector(
                "Angela", "Angela.Malden@hynds.co.nz", "Hynds Pipe Systems Limited"
            ),
            PersonSelector(
                "Angela Madden",
                "Angela.Malden@hynds.co.nz",
                "Hynds Pipe Systems Limited",
            ),
        ),
        expected_people=2,
        evidence="production jobs Angela=1, Angela Madden=0; shared email angela.malden@hynds.co.nz",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Arno Eramus", None, "HV Power Measurements and Protection Ltd"
        ),
        members=(
            PersonSelector(
                "Arno Eramus", None, "HV Power Measurements and Protection Ltd"
            ),
            PersonSelector(
                "Arno Erasmus",
                "arnoe@hvpowerautomation.com",
                "HV Power Measurements and Protection Ltd",
            ),
        ),
        expected_people=2,
        evidence="production jobs Arno Eramus=2, Arno Erasmus=1; shared phone +64212429114",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Arron Brown", "Arron@solutionzelectrical.co.nz", "CASH SALE - Arron Brown"
        ),
        members=(
            PersonSelector(
                "Aaron Brown",
                "aaron@solutionzelectrical.co.nz",
                "CASH SALE - Arron Brown",
            ),
            PersonSelector(
                "Arron Brown",
                "Arron@solutionzelectrical.co.nz",
                "CASH SALE - Arron Brown",
            ),
        ),
        expected_people=2,
        evidence="production jobs Aaron Brown=0, Arron Brown=1; shared phone +6421572121",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "AZAM SHAH", "azampanelbeater@hotmail.copm", "CASH SALE - AZ PANELS REPAIRS"
        ),
        members=(
            PersonSelector("AZAM", "azampanelbeater@hotmail.com", "Azam 021677855"),
            PersonSelector(
                "AZAM SHAH",
                "azampanelbeater@hotmail.copm",
                "CASH SALE - AZ PANELS REPAIRS",
            ),
        ),
        expected_people=2,
        evidence="production jobs AZAM=1, AZAM SHAH=1; shared phone +6421677855",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Ben King", None, "Snowdon Consulting"),
        members=(
            PersonSelector("Ben King", None, "Snowdon Consulting"),
            PersonSelector("Ben King", "ben@leapinnovation.nz", "Ben King"),
        ),
        expected_people=2,
        evidence="production jobs Ben King=1, Ben King=1; shared phone +64275259552",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Blayne Newton", None, "acryfab"),
        members=(
            PersonSelector("Blayne Newton", None, "acryfab"),
            PersonSelector(
                "BLAYNE NEWTON", "BLAYNE@ACRYFAB.CO.NZ", "CASH SALE - BLAYNE NEWTON"
            ),
        ),
        expected_people=2,
        evidence="production jobs Blayne Newton=1, BLAYNE NEWTON=1",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Bob Lopesi", "spares@elsnz.co.nz", "CASH SALE - ELS New Zealand"
        ),
        members=(
            PersonSelector(
                "Bob Lopesi", "Bob.Lopesi@elsnz.co.nz", "ELS New Zealand Limited"
            ),
            PersonSelector(
                "Bob Lopesi", "Bob@elsnz.co.nz", "CASH SALE - Econic Laundry Solutions"
            ),
            PersonSelector(
                "Bob Lopesi", "spares@elsnz.co.nz", "CASH SALE - ELS New Zealand"
            ),
        ),
        expected_people=3,
        evidence="production jobs Bob Lopesi=0, Bob Lopesi=1, Bob Lopesi=1",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Bobby", None, "Blackstone Project Management"),
        members=(
            PersonSelector("Bobby", None, "Blackstone Project Management"),
            PersonSelector("Bobby", None, "MSM (Shop)"),
            PersonSelector("Bobby prajitno", None, "Blackstone Project Management"),
        ),
        expected_people=3,
        evidence="production jobs Bobby=2, Bobby=1, Bobby prajitno=1; shared phone +642108817930",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "BRETT JOHNSON", "brett.johnson@nzstarch.co.nz", "NZ STARCH"
        ),
        members=(
            PersonSelector(
                "BRETT JOHNSON", "brett.johnson@nzstarch.co.nz", "NZ STARCH"
            ),
            PersonSelector(
                "BRETT JOHNSON", "brett@nzstarch.co.nz", "NEW ZEALAND STARCH"
            ),
        ),
        expected_people=2,
        evidence="production jobs BRETT JOHNSON=1, BRETT JOHNSON=1; shared phone +64273005151",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "BRONNY JACKSON",
            "bronwyn.jackson@xtra.co.nz",
            "CASH SALE - BRONWYN JACKSON",
        ),
        members=(
            PersonSelector("Bronnie", None, "Bronnie 02102255430"),
            PersonSelector(
                "BRONNY JACKSON",
                "bronwyn.jackson@xtra.co.nz",
                "CASH SALE - BRONWYN JACKSON",
            ),
        ),
        expected_people=2,
        evidence="production jobs Bronnie=1, BRONNY JACKSON=2; shared phone +642102255430",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "BYRON CRAWFORD",
            "ByronC@mcguinness.co.nz",
            "LT McGuinness Auckland Limited",
        ),
        members=(
            PersonSelector(
                "BYRON", "ByronC@mcguinness.co.nz", "CASH SALE - LT MCGUINESS"
            ),
            PersonSelector(
                "BYRON CRAWFORD",
                "ByronC@mcguinness.co.nz",
                "LT McGuinness Auckland Limited",
            ),
        ),
        expected_people=2,
        evidence="production jobs BYRON=0, BYRON CRAWFORD=4; shared email byronc@mcguinness.co.nz; shared phone +6421527295",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Charlie Thomlinson", None, "Snowdon Consulting"),
        members=(
            PersonSelector("Charlie", None, "Snowdon Consulting"),
            PersonSelector("Charlie Thomlinson", None, "Snowdon Consulting"),
            PersonSelector("Charlie Thomlinson", None, "Snowden"),
        ),
        expected_people=3,
        evidence="production jobs Charlie=1, Charlie Thomlinson=6, Charlie Thomlinson=1; shared phone +642108658458",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Chris Baybut",
            "Chris.Baybut@cushwake.com",
            "Cushman and Wakefield New Zealand Limited",
        ),
        members=(
            PersonSelector("CHRIS", None, "Cushman and Wakefield New Zealand Limited"),
            PersonSelector(
                "Chris Baybut",
                "Chris.Baybut@cushwake.com",
                "Cushman and Wakefield New Zealand Limited",
            ),
            PersonSelector(
                "Cushman wakefield Chris",
                None,
                "Cushman and Wakefield New Zealand Limited",
            ),
        ),
        expected_people=3,
        evidence="production jobs CHRIS=1, Chris Baybut=6, Cushman wakefield Chris=1; shared phone +64274558373",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "CHRISTOPHER WATT", "christopher@interiordb.co.nz", "INTERIOR DB LIMITED"
        ),
        members=(
            PersonSelector(
                "Chris Watt",
                "christopher@interiordb.co.nz",
                "CASH SALE - CHRISTOPHER WATT",
            ),
            PersonSelector(
                "CHRISTOPHER WATT",
                "christopher@interiordb.co.nz",
                "INTERIOR DB LIMITED",
            ),
        ),
        expected_people=2,
        evidence="production jobs Chris Watt=0, CHRISTOPHER WATT=3; shared email christopher@interiordb.co.nz; shared phone +64275382037",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "CRAIG BOYD", "dexterdut@gmail.com", "CASH SALE - CRAIG BOYD"
        ),
        members=(
            PersonSelector(
                "CRAIG BOYD", "dexterdut@gmail.com", "CASH SALE - CRAIG BOYD"
            ),
            PersonSelector(
                "CRAIR BOYD", "dexterdut@gmail.com", "CASH SALE - CRAIG BOYD"
            ),
        ),
        expected_people=2,
        evidence="production jobs CRAIG BOYD=0, CRAIR BOYD=1; shared email dexterdut@gmail.com",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Dane Charman", None, "Direct Control"),
        members=(
            PersonSelector("DANE CHARMAN", None, "Direct Control"),
            PersonSelector("Dane Charman", None, "Direct Control"),
        ),
        expected_people=2,
        evidence="production jobs DANE CHARMAN=0, Dane Charman=2",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Danny Newberry", "djnewberry1@gmail.com", "NZ Crane Hire Limited"
        ),
        members=(
            PersonSelector(
                "Danny Newberry", "djnewberry1@gmail.com", "NZ Crane Hire Limited"
            ),
            PersonSelector(
                "DANNY NEWBERRY", "djnewberry1@gmail.com", "Danny - NZ Crane"
            ),
        ),
        expected_people=2,
        evidence="production jobs Danny Newberry=3, DANNY NEWBERRY=1; shared phone +6421747065",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Dave", None, "CASH SALE - Dave Booth"),
        members=(
            PersonSelector("Dave", None, "CASH SALE - Dave Booth"),
            PersonSelector(
                "DAVID BOOTH", "CARPENTERDAVEBOOTH@GMAIL.COM", "CASH SALE - DAVID BOOTH"
            ),
        ),
        expected_people=2,
        evidence="production jobs Dave=1, DAVID BOOTH=1; shared phone +642102631588",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Dave", None, "Guardsman Security Services Limited"),
        members=(
            PersonSelector("Dave", None, "Guardsman Security Services Limited"),
            PersonSelector("DAVE YANALA", None, "Kiwi Alarms Ltd"),
            PersonSelector("DEV YANDA", None, "Guardsman Security Services Limited"),
        ),
        expected_people=3,
        evidence="production jobs Dave=9, DAVE YANALA=0, DEV YANDA=1; shared phone +64225084642",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Dave Allan", "iplmaintenance@yahoo.com", "IPL Maintenance"
        ),
        members=(
            PersonSelector(
                "Dave Allan", "iplmaintenance@yahoo.com", "CASH SALE - IPL maintenance"
            ),
            PersonSelector("Dave Allan", "iplmaintenance@yahoo.com", "IPL Maintenance"),
        ),
        expected_people=2,
        evidence="production jobs Dave Allan=1, Dave Allan=6; shared email iplmaintenance@yahoo.com; shared phone +64274884866",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "David White", "David.White@fisherpaykel.com", "Fisher and Paykel"
        ),
        members=(
            PersonSelector(
                "david white", "David.White@fisherpaykel.com", "Fisher and Paykel"
            ),
            PersonSelector(
                "David White", "David.White@fisherpaykel.com", "Fisher and Paykel"
            ),
        ),
        expected_people=2,
        evidence="production jobs david white=0, David White=13; shared email david.white@fisherpaykel.com",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Dion smit .", "dion.smit@dunninghams.co.nz", "D M Dunningham Limited"
        ),
        members=(
            PersonSelector(
                "DION SMIT", "dion.smit@dunninghams.co.nz", "Dion - Dunninghams"
            ),
            PersonSelector(
                "Dion smit .", "dion.smit@dunninghams.co.nz", "D M Dunningham Limited"
            ),
        ),
        expected_people=2,
        evidence="production jobs DION SMIT=0, Dion smit .=2; shared email dion.smit@dunninghams.co.nz; shared phone +64275556091",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "ED MACDONALD", "EMacDonald@htsgroup.co.nz", "HTS Group LTD - Ed Macdonald"
        ),
        members=(
            PersonSelector(
                "ED MACDONALD",
                "EMacDonald@htsgroup.co.nz",
                "HTS Group LTD - Ed Macdonald",
            ),
            PersonSelector(
                "Ed Macdonald", "emacdonald@htsgroup.co.nz", "HTS Group Ltd"
            ),
        ),
        expected_people=2,
        evidence="production jobs ED MACDONALD=1, Ed Macdonald=0; shared email emacdonald@htsgroup.co.nz; shared phone +64272412956",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Edwin Rysenberry", "erysenbry@mac.com", "CASH SALE - Edwin Rysenberry"
        ),
        members=(
            PersonSelector(
                "Edin Rysenberry", "erysenbry@mac.com", "CASH SALE - Edwin Rysenberry"
            ),
            PersonSelector(
                "Edwin Rysenberry", "erysenbry@mac.com", "CASH SALE - Edwin Rysenberry"
            ),
        ),
        expected_people=2,
        evidence="production jobs Edin Rysenberry=0, Edwin Rysenberry=1; shared email erysenbry@mac.com; shared phone +6421731454",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "ELIJAH HARIDAS",
            "ELIJAHRAULHARIDAS@GMAIL.COM",
            "CASH SALE - ELIJAH HARIDAS",
        ),
        members=(
            PersonSelector(
                "ELIJAH HARIDAS",
                "ELIJAHRAULHARIDAS@GMAIL.COM",
                "CASH SALE - ELIJAH HARIDAS",
            ),
        ),
        expected_people=2,
        evidence="production jobs ELIJAH HARIDAS=0, ELIJAH HARIDAS=1; shared email elijahraulharidas@gmail.com; shared phone +642904302129",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("EMILIO RUEDA", None, "PB Traffic"),
        members=(
            PersonSelector("EMILIO RUEDA", None, "PB Traffic"),
            PersonSelector("EMILIO RUEDA", None, "PB traffic solutions"),
        ),
        expected_people=2,
        evidence="production jobs EMILIO RUEDA=1, EMILIO RUEDA=0; shared phone +64272097842",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Ernesto", None, "CASH SALE#edenpark panel and paint"),
        members=(
            PersonSelector("Ernesto", None, "CASH SALE#edenpark panel and paint"),
            PersonSelector("Ernesto", None, "Eden park panel and paint"),
        ),
        expected_people=2,
        evidence="production jobs Ernesto=1, Ernesto=0; shared phone +6421629559",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Gareth Taripo", "gareth@gast.co.nz", "CASH SALE - Gaast Automotive"
        ),
        members=(
            PersonSelector("Gareth", None, "CASH SALE - Gaast Automotive"),
            PersonSelector(
                "Gareth Taripo", "gareth@gast.co.nz", "CASH SALE - Gaast Automotive"
            ),
        ),
        expected_people=2,
        evidence="production jobs Gareth=0, Gareth Taripo=1; shared phone +64212616893",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Gary Lawrence", None, "CASH SALE - GARY LAWRENCE"),
        members=(
            PersonSelector("Gary Lawrence", None, "CASH SALE - GARY LAWRENCE"),
            PersonSelector("Gary Lawrence", None, "Garry Lawrence Roofing"),
        ),
        expected_people=2,
        evidence="production jobs Gary Lawrence=1, Gary Lawrence=1; shared phone +6421969601",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Gary McNabb", "gary@onsiteteam.co.nz", "Onsite Team"),
        members=(
            PersonSelector(
                "Gary Mcnabb", "gary@onsiteteam.co.nz", "Onsite Engineering Ltd"
            ),
            PersonSelector("Gary McNabb", "gary@onsiteteam.co.nz", "Onsite Team"),
        ),
        expected_people=2,
        evidence="production jobs Gary Mcnabb=0, Gary McNabb=18; shared email gary@onsiteteam.co.nz; shared phone +6421848568",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Geoff", None, "Geoff Bates"),
        members=(
            PersonSelector("Geoff", None, "Geoff Bates"),
            PersonSelector("Geoff Bates", None, "Geoff Bates"),
        ),
        expected_people=2,
        evidence="production jobs Geoff=1, Geoff Bates=1; shared phone +64204762687",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "GINA GASCOIGNE",
            "gina.gascoigne@aucklandcouncil.govt.nz",
            "Auckland Council",
        ),
        members=(
            PersonSelector(
                "GINA GASCOIGNE",
                "gina.gascoigne@aucklandcouncil.govt.nz",
                "Auckland Council",
            ),
            PersonSelector(
                "Gina Gascoigne",
                "gina.gascoigne@aucklandcouncil.govt.nz",
                "Auckland Council",
            ),
        ),
        expected_people=2,
        evidence="production jobs GINA GASCOIGNE=1, Gina Gascoigne=0; shared email gina.gascoigne@aucklandcouncil.govt.nz",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Glen Barratt", "fury@xtra.co.nz", "CASH SALE - Glen Barratt"
        ),
        members=(
            PersonSelector(
                "Glen Barratt", "fury@xtra.co.nz", "CASH SALE - Glen Barratt"
            ),
            PersonSelector(
                "GLENN BARRATT",
                "fury@xtra.co.nz",
                "CASH SALE - SUPERCITY COMMERCIAL INTERIORS LTD",
            ),
        ),
        expected_people=2,
        evidence="production jobs Glen Barratt=1, GLENN BARRATT=1; shared phone +64274888111",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Graeme", "onehungacarclinic@xtra.co.nz", "Onehunga Car Services Limited"
        ),
        members=(
            PersonSelector(
                "Graeme",
                "onehungacarclinic@xtra.co.nz",
                "Onehunga Car Services Limited",
            ),
            PersonSelector(
                "Graeme Mills",
                "onehunga.carclinic@xtra.co.nz",
                "Onehunga Car Services Limited",
            ),
        ),
        expected_people=2,
        evidence="production jobs Graeme=3, Graeme Mills=2; shared phone +6496342207",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "GUS KANJI", "guskanji@icloud.com", "CASH SALE - GUS KANJI"
        ),
        members=(
            PersonSelector("GUS KANJI", "guskanji@icloud.com", "CASH SALE - GUS KANJI"),
            PersonSelector("Gus Kanji", "guskanji@icloud.com", "Gus Kanji"),
        ),
        expected_people=2,
        evidence="production jobs GUS KANJI=4, Gus Kanji=2; shared email guskanji@icloud.com; shared phone +64274500727",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "HANDRO BIEWENGA", None, "MATERIAL HANDLING SOLUTIONS"
        ),
        members=(
            PersonSelector("Handro", None, "Handro"),
            PersonSelector("HANDRO BIEWENGA", None, "MATERIAL HANDLING SOLUTIONS"),
        ),
        expected_people=2,
        evidence="production jobs Handro=1, HANDRO BIEWENGA=1; shared phone +64212892852",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("HARSH", None, "Kiwi Alarms Ltd"),
        members=(
            PersonSelector("HARSH", None, "Kiwi Alarms Ltd"),
            PersonSelector("HARSH", None, "Guardsman Security Services Limited"),
        ),
        expected_people=2,
        evidence="production jobs HARSH=0, HARSH=0",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Henry", None, "Orams Marine Ltd"),
        members=(
            PersonSelector("Henry", None, "Orams Marine Ltd"),
            PersonSelector("Henry.", None, "Orams Marine Ltd"),
        ),
        expected_people=2,
        evidence="production jobs Henry=3, Henry.=1",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "IAIN MATTHEW",
            "ANNETTEMATTHEW1970@GMAIL.COM",
            "CASH SALE - NEW GENERATION OPERATIONS",
        ),
        members=(
            PersonSelector(
                "IAIN MATTHEW",
                "ANNETTEMATTHEW1970@GMAIL.COM",
                "CASH SALE - NEW GENERATION OPERATIONS",
            ),
            PersonSelector(
                "IAN MATTHEW", "annettematthew1970@gmail.com", "Ian Matthew"
            ),
        ),
        expected_people=2,
        evidence="production jobs IAIN MATTHEW=1, IAN MATTHEW=1; shared phone +64274754864",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("IRVING", None, "CASH SALE - IRVING"),
        members=(
            PersonSelector("IRVING", None, "CASH SALE - IRVING"),
            PersonSelector("Irving", None, "CASH SALE -Irving"),
        ),
        expected_people=2,
        evidence="production jobs IRVING=2, Irving=1; shared phone +6421378335",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Jason Hu", None, "Free Co Flooring"),
        members=(
            PersonSelector("Jason Hu", None, "Free Co Flooring"),
            PersonSelector(
                "jason Hu", "jason@freecoflooring.co.nz", "CASH SALE - Jason Hu"
            ),
        ),
        expected_people=2,
        evidence="production jobs Jason Hu=4, jason Hu=0; shared phone +642108588883",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Jenny Stevens", None, "Jenny Stevens"),
        members=(
            PersonSelector("Jenny Stevens", None, "Jenny Stevens"),
            PersonSelector(
                "Jenny Stevens", "jennifersteven@gmail.com", "CASH SALE - Jenny stevens"
            ),
        ),
        expected_people=2,
        evidence="production jobs Jenny Stevens=1, Jenny Stevens=1; shared phone +64210583499",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Jerry Friar", None, "Jerry Friar"),
        members=(
            PersonSelector("Jerry Friar", None, "Jerry Friar"),
            PersonSelector(
                "JERRY FRIAR",
                "jerry.friar@jameshardie.co.nz",
                "CASH SALE - Jerry Friar",
            ),
        ),
        expected_people=2,
        evidence="production jobs Jerry Friar=1, JERRY FRIAR=1; shared phone +6421563894",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "John Blacklock", "john@originbuild.co.nz", "Origin Build"
        ),
        members=(
            PersonSelector("John Blacklock", "john@originbuild.co.nz", "Origin Build"),
            PersonSelector("John Laycock", None, "Origin Build"),
        ),
        expected_people=2,
        evidence="production jobs John Blacklock=2, John Laycock=1; shared phone +64212461388",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Joseph Haydock", None, "Joseph Haydock"),
        members=(
            PersonSelector("Joesph Haydock", None, "Joesph Haydock"),
            PersonSelector("Joseph Haydock", None, "Joseph Haydock"),
        ),
        expected_people=2,
        evidence="production jobs Joesph Haydock=1, Joseph Haydock=1; shared phone +642040142511",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Josh Loughnan", "josh@wekatravel.com", "CASH SALE WEKA TRAVEL"
        ),
        members=(
            PersonSelector(
                "Josh Loughnan", "josh@wekatravel.com", "CASH SALE WEKA TRAVEL"
            ),
            PersonSelector(
                "Josh Loughnan", "josh@wekatravel.com", "Loughnan Construction"
            ),
        ),
        expected_people=2,
        evidence="production jobs Josh Loughnan=1, Josh Loughnan=1; shared email josh@wekatravel.com; shared phone +64220966480",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Lars", None, "Davison Construction"),
        members=(
            PersonSelector("Lard", None, "Davison Construction"),
            PersonSelector("Lars", None, "Davison Construction"),
            PersonSelector(
                "LARS DAVISON", "lars@davison.kiwi", "CASH SALE - LARS DAVISON"
            ),
        ),
        expected_people=3,
        evidence="production jobs Lard=1, Lars=3, LARS DAVISON=2; shared phone +64274052692",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Lee / Jeanette", None, "Lee & Jeanette Sutton"),
        members=(
            PersonSelector("Lee / Jeanette", None, "Lee & Jeanette Sutton"),
            PersonSelector(
                "Lee and Jeanette,cut mild steel plate with holes",
                None,
                "Lee and Jeanette Sutton",
            ),
        ),
        expected_people=2,
        evidence="production jobs Lee / Jeanette=1, Lee and Jeanette,cut mild steel plate with holes=1; shared phone +6421904199",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Madi Johns", "MADIJ@WATERFORD.CO.NZ", "Waterford Security Limited"
        ),
        members=(
            PersonSelector("MADI 2", None, "Waterford Security Limited"),
            PersonSelector(
                "Madi Johns", "MADIJ@WATERFORD.CO.NZ", "Waterford Security Limited"
            ),
        ),
        expected_people=2,
        evidence="production jobs MADI 2=0, Madi Johns=4; shared phone +64211901935",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Mark Homan", "markhoman41@gmail.com", "Ripout NZ Ltd"
        ),
        members=(
            PersonSelector("Mark Homan", None, "CASH SALE - Mark Homan"),
            PersonSelector("Mark Homan", "markhoman41@gmail.com", "Ripout NZ Ltd"),
        ),
        expected_people=2,
        evidence="production jobs Mark Homan=0, Mark Homan=4; shared phone +6421744827",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Mark Langdon", "mark@langdon.nz", "Mark Langdon"),
        members=(
            PersonSelector("MARK LANGDON", "mark@langdon.nz", "Mark Langdon"),
            PersonSelector("Mark Langdon", "mark@langdon.nz", "Mark Langdon"),
        ),
        expected_people=2,
        evidence="production jobs MARK LANGDON=1, Mark Langdon=1; shared phone +6421726479",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "MARK SEARS", "msears@customcontrols.co.nz", "Custom Controls Ltd"
        ),
        members=(
            PersonSelector(
                "MARK SEARS", "msears@customcontrols.co.nz", "Custom Controls Ltd"
            ),
            PersonSelector(
                "MARK SEARS", "msears@customcontrols.co.nz", "CASH SALE - MARK SEARS"
            ),
        ),
        expected_people=2,
        evidence="production jobs MARK SEARS=1, MARK SEARS=0; shared email msears@customcontrols.co.nz; shared phone +6421758031",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("MARSH COOPER", None, "CASH SALE - MARSH COOPER"),
        members=(
            PersonSelector("Marsh", None, "Marsh"),
            PersonSelector("MARSH COOPER", None, "CASH SALE - MARSH COOPER"),
        ),
        expected_people=2,
        evidence="production jobs Marsh=1, MARSH COOPER=1; shared phone +6421920315",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Matt green", None, "Penrose Paper Engineering"),
        members=(
            PersonSelector(
                "Matt -Kindactics", "matt@kidantics.co.nz", "CASH SALE - Kindactics"
            ),
            PersonSelector("Matt green", None, "Penrose Paper Engineering"),
            PersonSelector("Matt Green", "matt@kidantics.co.nz", "Matt Green"),
        ),
        expected_people=3,
        evidence="production jobs Matt -Kindactics=1, Matt green=1, Matt Green=1; shared email matt@kidantics.co.nz; shared phone +64212242900",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "MATTHEW MACDONALD", "Matthew.Macdonald@wmetals.co.nz", "Wakefield Metals"
        ),
        members=(
            PersonSelector(
                "MATHEW MCDONALD",
                "matthew.macdonald@wmetals.co.nz",
                "CASH SALE - WAKEFIELDS METALS",
            ),
            PersonSelector(
                "MATTHEW MACDONALD",
                "Matthew.Macdonald@wmetals.co.nz",
                "Wakefield Metals",
            ),
        ),
        expected_people=2,
        evidence="production jobs MATHEW MCDONALD=0, MATTHEW MACDONALD=1; shared email matthew.macdonald@wmetals.co.nz; shared phone +64212426732",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Michael Chee", "Michael@highmark.co.nz", "High Mark Foods"
        ),
        members=(
            PersonSelector("??", "Michael@highmark.co.nz", "High Mark Foods"),
            PersonSelector("Michael Chee", "Michael@highmark.co.nz", "High Mark Foods"),
            PersonSelector(
                "MICHAEL CHEE", "michael@highmark.co.nz", "CASH SALE - MICHAEL CHEE"
            ),
            PersonSelector("Mike", None, "High Mark Foods"),
        ),
        expected_people=4,
        evidence="production jobs ??=0, Michael Chee=3, MICHAEL CHEE=2, Mike=0; shared email michael@highmark.co.nz; shared phone +6421673290",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Mike", None, "Mike (Michael) Loomb"),
        members=(
            PersonSelector("Mike", None, "Mike (Michael) Loomb"),
            PersonSelector("Mike Loomb", None, "CASH SALE - Mike Loomb"),
        ),
        expected_people=2,
        evidence="production jobs Mike=1, Mike Loomb=0; shared phone +64211951166",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Mike Lum", "mikelum@email.com", "CASH SALE - Jack Lum and Co."
        ),
        members=(
            PersonSelector("Mike Lum", "mikelum@email.com", "Jack Lum and Co Limited"),
            PersonSelector(
                "Mike Lum", "mikelum@email.com", "CASH SALE - Jack Lum and Co."
            ),
        ),
        expected_people=2,
        evidence="production jobs Mike Lum=0, Mike Lum=1; shared email mikelum@email.com; shared phone +6421301188",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Nav",
            "navneet.singh1@cushwake.com",
            "Cushman and Wakefield New Zealand Limited",
        ),
        members=(
            PersonSelector(
                "Cushman Wakefield ,Nave",
                None,
                "Cushman and Wakefield New Zealand Limited",
            ),
            PersonSelector(
                "Nav",
                "navneet.singh1@cushwake.com",
                "Cushman and Wakefield New Zealand Limited",
            ),
            PersonSelector("Nave", None, "Cushman and Wakefield New Zealand Limited"),
            PersonSelector(
                "Nave - Botany Woolworths",
                None,
                "Cushman and Wakefield New Zealand Limited",
            ),
        ),
        expected_people=4,
        evidence="production jobs Cushman Wakefield ,Nave=3, Nav=9, Nave=1, Nave - Botany Woolworths=1; shared phone +64212434604",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Neville", None, "Watercone ltd (Neville)"),
        members=(
            PersonSelector("Neville", None, "The water cone"),
            PersonSelector("Neville", None, "Watercone ltd (Neville)"),
        ),
        expected_people=2,
        evidence="production jobs Neville=1, Neville=2; shared phone +6421922819",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "NICK DUFFY", "nick@hunkineng.co.nz", "Hunkin Engineering"
        ),
        members=(
            PersonSelector("Nick Duffy", "nick@hunkineng.co.nz", "Hunkin Engineering"),
            PersonSelector("NICK DUFFY", "nick@hunkineng.co.nz", "Hunkin Engineering"),
        ),
        expected_people=2,
        evidence="production jobs Nick Duffy=0, NICK DUFFY=4; shared email nick@hunkineng.co.nz",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Nick Haines",
            "nhaines@nepgroup.com",
            "NEP Broadcast Services New Zealand Limited",
        ),
        members=(
            PersonSelector("Nick Haines", None, "CASH SALE - Nick Haines"),
            PersonSelector(
                "Nick Haines",
                "nhaines@nepgroup.com",
                "NEP Broadcast Services New Zealand Limited",
            ),
        ),
        expected_people=2,
        evidence="production jobs Nick Haines=0, Nick Haines=1",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Nick Hansen", "nickhprogresse@hotmail.co.nz", "CASH SALE Nick Hansen"
        ),
        members=(
            PersonSelector("Nick Hansen", None, "Nick Hansen"),
            PersonSelector(
                "Nick Hansen", "nickhprogresse@hotmail.co.nz", "CASH SALE Nick Hansen"
            ),
        ),
        expected_people=2,
        evidence="production jobs Nick Hansen=1, Nick Hansen=3; shared phone +64272968753",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Nigel", None, "MSM (Shop)"),
        members=(
            PersonSelector("Nigel", None, "MSM (Shop)"),
            PersonSelector("Nigel", None, "MSM"),
        ),
        expected_people=2,
        evidence="production jobs Nigel=3, Nigel=1",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Onker Goundar",
            "church.st.panelbeaters@gmail.com",
            "CASH SALE - Church St Motors",
        ),
        members=(
            PersonSelector(
                "ONKAR GOUNDAR",
                "church.st.panelbeaters@gmail.com",
                "CASH SALE - CHURCH ST PANELBEATERS",
            ),
            PersonSelector(
                "onkar goundar",
                "church.st.panelbeaters@gmail.com",
                "CASH SALE - Church Street Panelbeaters",
            ),
            PersonSelector(
                "Onker Goundar",
                "church.st.panelbeaters@gmail.com",
                "CASH SALE - Church St Motors",
            ),
        ),
        expected_people=3,
        evidence="production jobs ONKAR GOUNDAR=0, onkar goundar=1, Onker Goundar=3; shared email church.st.panelbeaters@gmail.com; shared phone +64275670142",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Paul O'Brien", "paulobrien575@gmail.com", "CASH SALE - PAUL O'BRIEN"
        ),
        members=(
            PersonSelector("PAUL O'BRIEN", "paul@timeworx.co.nz", "Timeworx"),
            PersonSelector(
                "Paul O'Brien", "paulobrien575@gmail.com", "CASH SALE - PAUL O'BRIEN"
            ),
        ),
        expected_people=2,
        evidence="production jobs PAUL O'BRIEN=2, Paul O'Brien=3; shared phone +64212837447",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Pete Pedersen", None, "CASH SALE#Pete Pederson"),
        members=(
            PersonSelector("Pete Pedersen", None, "CASH SALE#Pete Pederson"),
            PersonSelector(
                "Pete Pederson", "prodognz@gmail.com", "CASH SALE - Pete Pederson"
            ),
        ),
        expected_people=2,
        evidence="production jobs Pete Pedersen=1, Pete Pederson=1; shared phone +64274300224",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Peter", None, "Cushman and Wakefield New Zealand Limited"
        ),
        members=(
            PersonSelector("Peter", None, "Cushman and Wakefield New Zealand Limited"),
            PersonSelector(
                "Pieter Badenhorst",
                "pieter.badenhorst@cushwake.com",
                "Cushman and Wakefield New Zealand Limited",
            ),
        ),
        expected_people=2,
        evidence="production jobs Peter=5, Pieter Badenhorst=3; shared phone +6421466755",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "PETER MANHIRE", "peter.manhire@skellerupgroup.com", "Peter Manhire"
        ),
        members=(
            PersonSelector("Peter Manhire", None, "Ultralon Foam International"),
            PersonSelector(
                "PETER MANHIRE", "peter.manhire@skellerupgroup.com", "Peter Manhire"
            ),
        ),
        expected_people=2,
        evidence="production jobs Peter Manhire=1, PETER MANHIRE=1",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Phil", None, "Phil"),
        members=(
            PersonSelector("Phil", None, "Phil"),
            PersonSelector("Phil", None, "CASH SALE - VIKING BUILDERS LTD - PHIL"),
            PersonSelector("Phil", None, "CASH SALE - Phil"),
            PersonSelector("Philip", None, "Phil"),
        ),
        expected_people=4,
        evidence="production jobs Phil=1, Phil=1, Phil=0, Philip=1; shared phone +642108568997",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Philip Whitam", "phil.point@outlook.com", "Point Maintenance"
        ),
        members=(
            PersonSelector("Philip", None, "cash sale phillip"),
            PersonSelector("Philip", "phil.point@outlook.com", "Phillip Whitham"),
            PersonSelector(
                "Philip Whitam", "phil.point@outlook.com", "Point Maintenance"
            ),
        ),
        expected_people=3,
        evidence="production jobs Philip=1, Philip=1, Philip Whitam=4; shared email phil.point@outlook.com; shared phone +64277033500",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Ray Zhang", "ray.zhang@hellofresh.co.nz", "Hello Fresh New Zealand"
        ),
        members=(
            PersonSelector(
                "Ray Zhang", "ray.zhang@hellofresh.co.nz", "Hello Fresh New Zealand"
            ),
            PersonSelector(
                "RAY ZHANG", "ray.zhang@hellofresh.co.nz", "Hello Fresh New Zealand"
            ),
        ),
        expected_people=2,
        evidence="production jobs Ray Zhang=9, RAY ZHANG=0; shared email ray.zhang@hellofresh.co.nz",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "REM WADEH", "REM.WADEH@HOTMAIL.COM", "CASH SALE - REM WADEH"
        ),
        members=(
            PersonSelector(
                "REM WADEH", "REM.WADEH@HOTMAIL.COM", "CASH SALE - REM WADEH"
            ),
            PersonSelector(
                "REM WADEH", "rem_wadeh@hotmail.com", "CASH - SALE - RERM WADEH"
            ),
        ),
        expected_people=2,
        evidence="production jobs REM WADEH=2, REM WADEH=0; shared phone +64211523239",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Richard Mills", None, "Cushman and Wakefield New Zealand Limited"
        ),
        members=(
            PersonSelector(
                "Richard Mills", None, "Cushman and Wakefield New Zealand Limited"
            ),
            PersonSelector(
                "Richard Mills",
                "graememills15@gmail.com",
                "Onehunga Car Services Limited",
            ),
        ),
        expected_people=2,
        evidence="production jobs Richard Mills=10, Richard Mills=1",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Rick Van Swet", "rickvanswet@gmail.com", "CASH SALE - Rick Van Swet"
        ),
        members=(
            PersonSelector("Rick", None, "Rick vanderset"),
            PersonSelector(
                "Rick Van Swet", "rickvanswet@gmail.com", "CASH SALE - Rick Van Swet"
            ),
        ),
        expected_people=2,
        evidence="production jobs Rick=1, Rick Van Swet=1; shared phone +6421400711",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Rob", None, "Expac Machining Centre 2024 Ltd"),
        members=(
            PersonSelector(
                "Expac   cut and fold brackets as per drawing",
                None,
                "Expac Machining Centre 2024 Ltd",
            ),
            PersonSelector("Rob", None, "Expac Machining Centre 2024 Ltd"),
        ),
        expected_people=2,
        evidence="production jobs Expac   cut and fold brackets as per drawing=1, Rob=5; shared phone +64274448238",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Robbie", None, "Robbie Grant"),
        members=(
            PersonSelector("Robbie", None, "Robbie Grant"),
            PersonSelector("Robert Grant", None, "Robert Grant"),
        ),
        expected_people=2,
        evidence="production jobs Robbie=1, Robert Grant=1; shared phone +6421502802",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Robert", None, "Cushman and Wakefield New Zealand Limited"
        ),
        members=(
            PersonSelector("Robert", None, "Cushman and Wakefield New Zealand Limited"),
            PersonSelector("ROBERT", None, "cash sale - ROBERT - CUSHMAN WAKEFIELD"),
        ),
        expected_people=2,
        evidence="production jobs Robert=15, ROBERT=2; shared phone +64212450109",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Rusty Tagicakibau",
            "Rusty.Tagicakibau@cushwake.com",
            "Cushman and Wakefield New Zealand Limited",
        ),
        members=(
            PersonSelector("Rusty", None, "Rusty Tagicakibau"),
            PersonSelector(
                "Rusty Tagicakibau",
                "Rusty.Tagicakibau@cushwake.com",
                "Cushman and Wakefield New Zealand Limited",
            ),
        ),
        expected_people=2,
        evidence="production jobs Rusty=1, Rusty Tagicakibau=6; shared phone +64274050629",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Sam Loughnan", "sam@loughnanconstruction.co.nz", "Loughnan Construction"
        ),
        members=(
            PersonSelector("Sam", None, "Loughnan Construction"),
            PersonSelector(
                "Sam Loughnan",
                "sam@loughnanconstruction.co.nz",
                "Loughnan Construction",
            ),
        ),
        expected_people=2,
        evidence="production jobs Sam=4, Sam Loughnan=5; shared phone +6421782110",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Sarah newman", None, "CGO (Corporate) Limited"),
        members=(
            PersonSelector("Sarah newman", None, "CGO (Corporate) Limited"),
            PersonSelector(
                "Sarah Newman", "accounts@mammothbrands.nz", "CGO Corporate Ltd"
            ),
            PersonSelector(
                "Sarah Newman", "sarah@mammothbrands.nz", "CASH SALE - Mammoth Brands"
            ),
        ),
        expected_people=3,
        evidence="production jobs Sarah newman=4, Sarah Newman=1, Sarah Newman=0; shared phone +64212727246",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Simon", None, "Simon Cope"),
        members=(
            PersonSelector("Simon", None, "Simon Cope"),
            PersonSelector("Simon Cope", None, "Simon Cope"),
        ),
        expected_people=2,
        evidence="production jobs Simon=1, Simon Cope=1; shared phone +6421968103",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Simon Rose", "simon.rose@proclimb.co.nz", "Proclimb"),
        members=(
            PersonSelector("Simon Rose", "simon.rose@proclimb.co.nz", "Proclimb"),
            PersonSelector(
                "SIMON ROSE", "simon.rose@proclimb.co.nz", "CASH SALE - SIMON ROSE"
            ),
        ),
        expected_people=2,
        evidence="production jobs Simon Rose=1, SIMON ROSE=1; shared email simon.rose@proclimb.co.nz; shared phone +64276642307",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "STEPHEN CARR", "daimlersteve@gmail.com", "CASH SALE - STEPHEN CARR"
        ),
        members=(
            PersonSelector(
                "STEPHEN CARR", "daimlersteve@gmail.com", "Stephen (Steve) Carr"
            ),
            PersonSelector(
                "STEPHEN CARR", "daimlersteve@gmail.com", "CASH SALE - STEPHEN CARR"
            ),
            PersonSelector(
                "Steve Carr", "daimlersteve@gmail.com", "CASH SALE - Steve Carr"
            ),
        ),
        expected_people=3,
        evidence="production jobs STEPHEN CARR=1, STEPHEN CARR=1, Steve Carr=1; shared email daimlersteve@gmail.com; shared phone +64275120443",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Steve Kirby", "kirby.nz@gmail.com", "CASH SALE - Steve Kirby"
        ),
        members=(
            PersonSelector("Steve", "Kirby.nz@gmail.com", "Steve Kirby"),
            PersonSelector(
                "Steve Kirby", "kirby.nz@gmail.com", "CASH SALE - Steve Kirby"
            ),
        ),
        expected_people=2,
        evidence="production jobs Steve=1, Steve Kirby=1; shared email kirby.nz@gmail.com",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Stuart Watts", "stuartwatts07@gmail.com", "CASH SALE- Penrose motors"
        ),
        members=(
            PersonSelector(
                "Stuart Watts", "stuartwatts07@gmail.com", "CASH SALE- Penrose motors"
            ),
            PersonSelector(
                "STUART WATTS", "stuartwatts07@gmail.com", "CASH SALE - STUART WATTS"
            ),
        ),
        expected_people=2,
        evidence="production jobs Stuart Watts=1, STUART WATTS=1; shared phone +64278172546",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "SUZANNE PENTECOST",
            "spentecost@adinahotels.co.nz",
            "CASH SALE - ADINA APARTMENT HOTEL AUCKLAND BRITOMART",
        ),
        members=(
            PersonSelector(
                "SUZANNE PENTECOST",
                "spentecost@adinahotels.co.nz",
                "Dominion Constructors Limited",
            ),
            PersonSelector(
                "SUZANNE PENTECOST",
                "spentecost@adinahotels.co.nz",
                "CASH SALE - ADINA APARTMENT HOTEL AUCKLAND BRITOMART",
            ),
        ),
        expected_people=2,
        evidence="production jobs SUZANNE PENTECOST=0, SUZANNE PENTECOST=2; shared email spentecost@adinahotels.co.nz; shared phone +6493938200",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("Thomas", "redhawk@xtra.co.nz", "thomas"),
        members=(
            PersonSelector("Thomas", "redhawk@xtra.co.nz", "thomas"),
            PersonSelector("tom", "redhawk@xtra.co", "thomas"),
        ),
        expected_people=2,
        evidence="production jobs Thomas=1, tom=0; shared phone +64220446045",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Timothy Moore", "tim.moore@hussmann.com", "MC ALPINE HUSSMANN"
        ),
        members=(
            PersonSelector(
                "TIM MOORE", "tim.moore@hussmann.com", "CASH SALE - MCALPINE HUSSMANN"
            ),
            PersonSelector(
                "Timothy Moore", "tim.moore@hussmann.com", "MC ALPINE HUSSMANN"
            ),
        ),
        expected_people=2,
        evidence="production jobs TIM MOORE=2, Timothy Moore=2; shared email tim.moore@hussmann.com; shared phone +64272240844",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Toby Andrews", "tobias.andrews@ventia.com", "Ventia NZ Limited"
        ),
        members=(
            PersonSelector(
                "Tobias Andrews", "tobias.andrews@ventia.com", "Ventia NZ Limited"
            ),
            PersonSelector(
                "Toby Andrews", "tobias.andrews@ventia.com", "Ventia NZ Limited"
            ),
        ),
        expected_people=2,
        evidence="production jobs Tobias Andrews=1, Toby Andrews=6; shared phone +64273594960",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Vanya Kroon", "Vanyakroon@gmail.com", "CASH SALE - Vanya Kroon"
        ),
        members=(
            PersonSelector(
                "VANYA KROON", "VANYAKROON@GMIAL.COM", "CASH SALE - Vanya Kroon"
            ),
            PersonSelector(
                "Vanya Kroon", "Vanyakroon@gmail.com", "CASH SALE - Vanya Kroon"
            ),
        ),
        expected_people=2,
        evidence="production jobs VANYA KROON=1, Vanya Kroon=3; shared phone +64212046863",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "Vimlesh Prasad",
            "Vimlesh.Prasad@fultonhogan.com",
            "Fulton Hogan Auckland Limited",
        ),
        members=(
            PersonSelector(
                "Vimlesh Prasad",
                "Vimlesh.Prasad@fultonhogan.com",
                "Fulton Hogan Auckland Limited",
            ),
            PersonSelector(
                "Vimlesh Prasadd",
                "vimlesh.prasad@fultonhogan.com",
                "Fulton Hogan Auckland Limited",
            ),
        ),
        expected_people=2,
        evidence="production jobs Vimlesh Prasad=17, Vimlesh Prasadd=1; shared email vimlesh.prasad@fultonhogan.com; shared phone +64278365351",
    ),
    PersonMergeDecision(
        canonical=PersonSelector("WOLFGANG", None, "CASH SALE - WOLFGANG"),
        members=(
            PersonSelector("Wolfgang", None, "Wolfgang Schenk"),
            PersonSelector("WOLFGANG", None, "CASH SALE - WOLFGANG"),
        ),
        expected_people=2,
        evidence="production jobs Wolfgang=1, WOLFGANG=2; shared phone +64211253754",
    ),
    PersonMergeDecision(
        canonical=PersonSelector(
            "ZACH LINDSAY",
            "mike@lindsaybuildingservices.co.nz",
            "CASH SALE - Lindsay Building Services",
        ),
        members=(
            PersonSelector(
                "ZACH",
                "ZACH@LINDSAYBUILDINGSERVICES.CO.NZ",
                "Lindsay Building Services",
            ),
            PersonSelector(
                "ZACH LINDSAY",
                "mike@lindsaybuildingservices.co.nz",
                "CASH SALE - Lindsay Building Services",
            ),
        ),
        expected_people=2,
        evidence="production jobs ZACH=1, ZACH LINDSAY=1; shared phone +64212216699",
    ),
)


# These are genuine separate businesses despite a weak shared signal.  This is
# the complete defence ledger for the broad production candidate review.
USER_APPROVED_RETAINED_COMPANY_DECISIONS: tuple[RetainedDecision, ...] = ()

AGENT_RETAINED_COMPANY_DECISIONS: tuple[RetainedDecision, ...] = (
    RetainedDecision(
        ("Auckland Airport Limited", "DGE Ltd"),
        "Aaron Williams has real jobs recorded for both organisations; one Person is linked to both.",
    ),
    RetainedDecision(
        (
            "Auckland Bead Blasting Services",
            "Westgate Welding Limited",
            "Galvanising Services 2018 Limited",
        ),
        "Only a Vodafone-hosted email domain is shared; the names and job histories are unrelated.",
    ),
    RetainedDecision(
        ("Auckland Council", "CASH SALE - Renee Bevan", "Kim Sinclair", "Mike Munley"),
        "Only the public me.com email domain is shared.",
    ),
    RetainedDecision(
        ("Body Corporate 322257", "Crockers Body Corp BC 312605"),
        "The legal body-corporate numbers are different.",
    ),
    RetainedDecision(
        ("Carter Holt Harvey - Infotech", "Carter Holt Harvey Paperbag"),
        "Named operating divisions with separate purchasing histories.",
    ),
    RetainedDecision(
        ("Carters Panmure", "Carters Onehunga - account 3079980"),
        "Named branches; branch identity is required for delivery and billing.",
    ),
    RetainedDecision(
        ("CASH SALE - FRESH CHOICE ONEHUNGA", "Fresh Choice Mangere Bridge"),
        "Different supermarket branches.",
    ),
    RetainedDecision(
        ("CASH SALE - New World Orakei", "New World Green Bay", "New World New Lynn"),
        "Different supermarket branches.",
    ),
    RetainedDecision(
        (
            "CASH SALE - Rana Property Maintenance",
            "CASH SALE - Matt Heywood",
            "Garry Lawrence Roofing",
            "Reece Taituha",
            "Super Cheap Tyres",
        ),
        "Only the public live.com email domain is shared.",
    ),
    RetainedDecision(
        ("Corrin Lakeland (corrin.lakeland@cmeconnect.com)", "Gerry Westenberg"),
        "Two named coworkers using the CME corporate domain.",
    ),
    RetainedDecision(
        (
            "Craig Burrowes",
            "Electrical Importing Company",
            "Tom Morris",
            "Watchman Developments Ltd",
        ),
        "Only the legacy ihug ISP domain is shared.",
    ),
    RetainedDecision(
        ("Expac Engineering Ltd (new account)", "Expac Machining Centre 2024 Ltd"),
        "Separate incorporated machining business: seven machining jobs for Rob and Steve.  Only the old Expac contact details overlap.",
    ),
    RetainedDecision(
        ("Galeeco Automotive", "CASH SALE - MULTISERVE"),
        "Different businesses and named contacts; a family/office phone is shared.",
    ),
    RetainedDecision(
        ("George Western Foods Limited - Tip Top Bread Auckland", "Mauri"),
        "Separate operating divisions sharing accounts-payable infrastructure.",
    ),
    RetainedDecision(
        ("Global Fire Limited", "Global Linings Ltd"),
        "Sister legal companies with shared administration.",
    ),
    RetainedDecision(
        (
            "CASH SALE - IDEAL ELECTRICAL ROSEDALE BRANCH",
            "Ideal Electrical (Penrose) - Cash sale purchases",
        ),
        "Different electrical-supply branches.",
    ),
    RetainedDecision(
        ("Kinect Holdings Ltd", "Brickell Technology"),
        "Only the ieee.org membership domain is shared.",
    ),
    RetainedDecision(
        ("KSG Food Packers Ltd", "Green Valley Foods"),
        "Related but separately named and billed food businesses.",
    ),
    RetainedDecision(
        ("Leap Innovation NZ", "Snowdon Consulting"),
        "Ben has genuine job history at both companies.",
    ),
    RetainedDecision(
        (
            "Liquorland Onehunga",
            "Liquorland Stonefield",
            "Premium Liquor - Liquorland Onehunga",
        ),
        "Different retail branches/accounts.",
    ),
    RetainedDecision(
        ("CASH SALE WEKA TRAVEL", "Loughnan Construction"),
        "Josh Loughnan has genuine jobs at both; the companies have unrelated work histories.",
    ),
    RetainedDecision(
        (
            "Bloomin Luvley",
            "Mike Gillard Family Trust",
            "Onehunga Auto and Marine Upholstery",
            "Tony Warren Engineering",
        ),
        "Only the legacy Orcon ISP domain is shared.",
    ),
    RetainedDecision(
        ("MSM (Billable - Customer TBD)", "Cash Sales"),
        "Deliberate internal workflow accounts with different accounting purposes.",
    ),
    RetainedDecision(
        (
            "MSM (Shop)",
            "MSM (Billable - Customer TBD)",
            "ABC Carpet Cleaning TEST IGNORE",
            "Lakeland Consulting",
        ),
        "Deliberate internal/test accounts; the abc/lakeland address is test data, not customer identity.",
    ),
    RetainedDecision(
        (
            "Oji Fibre Solutions - Packaging NZ",
            "Oji Fibre Solutions - Paper Bag",
            "Oji Fibre Solutions - Penrose Mill",
            "Penrose Paper Engineering",
        ),
        "Named Oji divisions are separate; Penrose Paper Engineering is a different current business despite Matt's obsolete Oji address.",
    ),
    RetainedDecision(
        ("Onehunga Car Services Limited", "Cushman and Wakefield New Zealand Limited"),
        "Richard Mills has real jobs under both companies and is represented by one Person linked to both.",
    ),
    RetainedDecision(
        ("Pauanui Menzshed", "Timeworx"),
        "Paul O'Brien's personal Gmail is the only overlap; the organisations are unrelated.",
    ),
    RetainedDecision(
        ("Peter Diamond", "Impact Tints"), "Only the public mail.com domain is shared."
    ),
    RetainedDecision(
        ("Ray Baker", "The Dunollie Group"),
        "Only the legacy Slingshot ISP domain is shared.",
    ),
    RetainedDecision(
        ("Regan Marshall (WWB)", "Richard Pryde - Winstones"),
        "Different GIB coworkers represented by person-labelled records.",
    ),
    RetainedDecision(
        ("Ripout NZ Ltd", "Workdek"),
        "Raw values are '0800 RIPOUT' and '0800nofall'; both were incorrectly normalised to +64800.",
    ),
    RetainedDecision(
        ("Road Science", "Downer Group"),
        "Subsidiary and parent are separately billed legal entities.",
    ),
    RetainedDecision(
        ("Ultralon Foam International", "Nexus Performance Foams Limited"),
        "Separate Skellerup subsidiaries; Peter's group contact is shared.",
    ),
    RetainedDecision(
        ("University of Auckland - Support Services", "Total Works Ltd"),
        "Separate organisations; only an aucklanduni contact address overlaps.",
    ),
    RetainedDecision(
        (
            "Valmont Coatings/CSP Galvanising",
            "Locker Group Limited/Webforge Locker (Valmont)",
            "Webforge (NZ) Ltd",
        ),
        "Separate operating divisions with distinct work histories.",
    ),
    RetainedDecision(
        ("Work Investment Ltd T/A Epic Beer", "Dominion Constructors Limited"),
        "Simon Mowday is a construction contact for Epic; the legal companies are unrelated.",
    ),
    RetainedDecision(
        ("Yellow Bites LImited", "JJ Wafer Biscuits Limited"),
        "Separate Limited billing entities under shared group accounts; Yellow Bites alone has eleven jobs.",
    ),
)


# Shared office numbers identify coworkers, not duplicate People.  The two
# cross-company entries are also supported by real job history at both firms.
USER_APPROVED_RETAINED_PERSON_DECISIONS: tuple[RetainedDecision, ...] = ()

AGENT_RETAINED_PERSON_DECISIONS: tuple[RetainedDecision, ...] = (
    RetainedDecision(
        ("BRENT", "Brian", "Nathan"),
        "Three Stainless Welding people share the office number; Brent has 94 jobs and Nathan has two.",
    ),
    RetainedDecision(
        ("David", "Mike"),
        "Equipment Engineering coworkers with different corporate emails and seven/six jobs.",
    ),
    RetainedDecision(
        ("Graeme", "Richard Mills"),
        "Different Onehunga Car Services people sharing the office number.",
    ),
    RetainedDecision(
        ("Hamish Taylor", "TOM TAULA"),
        "Matassa coworkers with different corporate emails and two jobs each.",
    ),
    RetainedDecision(
        ("JENNINE MARSHALL", "TYLER BROWN"),
        "GFL coworkers with different corporate emails and one job each.",
    ),
    RetainedDecision(
        ("Josh N.", "Raj"), "Different companies; abc@gmail.com is placeholder data."
    ),
    RetainedDecision(
        ("Keith Kariyawasam", "SURANGA KARIYAWASAM"),
        "Different Galeeco/Multiserve people sharing a family or office phone.",
    ),
    RetainedDecision(
        ("Mike", "Raj"),
        "Different Boss Motorbodies/AI Technology contacts sharing an office number.",
    ),
    RetainedDecision(
        ("Tamara Gogava", "Varinder Kumar"),
        "HV coworkers with different corporate emails and jobs.",
    ),
    RetainedDecision(
        ("tony", "ZACH LINDSAY"),
        "Different Lindsay Building Services contacts sharing the company number.",
    ),
)


INVALID_LINKS: tuple[InvalidLinkDecision, ...] = (
    InvalidLinkDecision(
        "MSM (Shop)",
        "Bobby",
        None,
        "Bobby's real Blackstone history proves the MSM Shop association is erroneous.",
    ),
    InvalidLinkDecision(
        "Dominion Constructors Limited",
        "SUZANNE PENTECOST",
        "spentecost@adinahotels.co.nz",
        "Suzanne is Adina's contact; Dominion has no supporting job history for this link.",
    ),
)

MATT_GREEN_REPAIR = PersonSelector(
    "Matthew Green", "j.green@northlandroofs.com", "CASH SALE-Kidantics"
)
MATT_WRONG_METHOD_VALUES = {"j.green@northlandroofs.com", "+64277003221"}


def _company_activity(company: Company) -> int:
    from apps.accounting.models import Bill, CreditNote, Invoice, Quote
    from apps.job.models import Job
    from apps.purchasing.models import PurchaseOrder

    return (
        Job.objects.filter(company=company).count()
        + Invoice.objects.filter(company=company).count()
        + Bill.objects.filter(company=company).count()
        + CreditNote.objects.filter(company=company).count()
        + Quote.objects.filter(company=company).count()
        + PurchaseOrder.objects.filter(supplier=company).count()
        + company.contacts.count()
        + company.contact_methods.count()
    )


def _person_activity(person: Person) -> int:
    from apps.crm.models import PhoneCallRecord
    from apps.job.models import Job

    return (
        Job.objects.filter(person=person).count()
        + PhoneCallRecord.objects.filter(person=person).count()
        + person.company_links.count()
        + person.contact_methods.count()
    )


def _resolve_company_decisions() -> list[tuple[Company, list[Company]]]:
    resolved: list[tuple[Company, list[Company]]] = []
    used_ids: set[str] = set()
    for decision in REVIEWED_COMPANY_MERGES:
        companies = list(Company.objects.filter(name__in=decision.names))
        if len(companies) != decision.expected_rows:
            raise RuntimeError(
                f"KAN-278 Company evidence changed for {decision.names}: "
                f"expected {decision.expected_rows}, found {len(companies)}"
            )
        canonical_candidates = [
            company for company in companies if company.name == decision.canonical_name
        ]
        if not canonical_candidates:
            raise RuntimeError(
                f"KAN-278 canonical Company is missing: {decision.canonical_name}"
            )
        canonical = max(canonical_candidates, key=_company_activity)
        sources = [company for company in companies if company.id != canonical.id]
        company_ids = {str(company.id) for company in companies}
        overlap = used_ids.intersection(company_ids)
        if overlap:
            raise RuntimeError(f"KAN-278 Company decisions overlap: {decision.names}")
        used_ids.update(company_ids)
        resolved.append((canonical, sources))
    return resolved


def _person_query(selector: PersonSelector) -> Q:
    query = Q(name=selector.name)
    if selector.email is None:
        query &= Q(email__isnull=True)
    else:
        query &= Q(email__iexact=selector.email)
    if selector.company_name is None:
        query &= Q(company_links__isnull=True)
    else:
        query &= Q(company_links__company__name=selector.company_name)
    return query


def _people_for_selector(selector: PersonSelector) -> list[Person]:
    return list(Person.objects.filter(_person_query(selector)).distinct())


def _resolve_person_decisions() -> list[tuple[Person, list[Person]]]:
    resolved: list[tuple[Person, list[Person]]] = []
    used_ids: set[str] = set()
    for decision in REVIEWED_PERSON_MERGES:
        people_by_id = {
            person.id: person
            for selector in decision.members
            for person in _people_for_selector(selector)
        }
        people = list(people_by_id.values())
        if len(people) != decision.expected_people:
            raise RuntimeError(
                f"KAN-278 Person evidence changed for {decision.members}: "
                f"expected {decision.expected_people}, found {len(people)}"
            )
        canonical_candidates = _people_for_selector(decision.canonical)
        canonical_candidates = [
            person for person in canonical_candidates if person.id in people_by_id
        ]
        if not canonical_candidates:
            raise RuntimeError(
                f"KAN-278 canonical Person is missing: {decision.canonical}"
            )
        canonical = max(canonical_candidates, key=_person_activity)
        sources = [person for person in people if person.id != canonical.id]
        person_ids = {str(person.id) for person in people}
        overlap = used_ids.intersection(person_ids)
        if overlap:
            raise RuntimeError(f"KAN-278 Person decisions overlap: {decision.members}")
        used_ids.update(person_ids)
        resolved.append((canonical, sources))
    return resolved


def _resolve_invalid_links() -> list[CompanyPersonLink]:
    links: list[CompanyPersonLink] = []
    for decision in INVALID_LINKS:
        queryset = CompanyPersonLink.objects.filter(
            company__name=decision.company_name,
            person__name=decision.person_name,
        )
        if decision.person_email is None:
            queryset = queryset.filter(person__email__isnull=True)
        else:
            queryset = queryset.filter(person__email__iexact=decision.person_email)
        matches = list(queryset)
        if len(matches) != 1:
            raise RuntimeError(
                f"KAN-278 invalid-link evidence changed for {decision}: "
                f"found {len(matches)}"
            )
        links.append(matches[0])
    return links


def _repair_matt_green() -> None:
    matches = _people_for_selector(MATT_GREEN_REPAIR)
    if len(matches) != 1:
        raise RuntimeError(f"KAN-278 Matt Green evidence changed: found {len(matches)}")
    person = matches[0]
    ContactMethod.objects.filter(
        person=person,
        normalized_value__in=MATT_WRONG_METHOD_VALUES,
    ).delete()
    person.email = None
    person.save(update_fields=["email", "updated_at"])


def _normalised_names(names: list[str]) -> frozenset[str]:
    return frozenset(" ".join(name.casefold().split()) for name in names)


def _assert_residuals_are_defended() -> None:
    report = DuplicateIdentityReportService().get_report()
    automatic = [
        group
        for group in report["company_groups"] + report["person_groups"]
        if group["recommendation"] == "merge"
    ]
    if automatic:
        raise RuntimeError(
            f"KAN-278 cleanup left {len(automatic)} unmerged duplicate groups"
        )

    retained_companies = {
        _normalised_names(list(decision.names))
        for decision in (
            USER_APPROVED_RETAINED_COMPANY_DECISIONS + AGENT_RETAINED_COMPANY_DECISIONS
        )
    }
    for company_group in report["company_groups"]:
        names = _normalised_names(
            [member["name"] for member in company_group["members"]]
        )
        if not any(names <= retained for retained in retained_companies):
            raise RuntimeError(
                f"KAN-278 has an undefended retained Company group: {sorted(names)}"
            )

    retained_people = {
        _normalised_names(list(decision.names))
        for decision in (
            USER_APPROVED_RETAINED_PERSON_DECISIONS + AGENT_RETAINED_PERSON_DECISIONS
        )
    }
    for person_group in report["person_groups"]:
        names = _normalised_names(
            [member["name"] for member in person_group["members"]]
        )
        if not any(names <= retained for retained in retained_people):
            raise RuntimeError(
                f"KAN-278 has an undefended retained Person group: {sorted(names)}"
            )


def _flatten_existing_company_merges(staff: Staff) -> None:
    company_rows = list(Company.objects.values_list("id", "merged_into_id"))
    company_ids = {company_id for company_id, _destination_id in company_rows}
    destinations = {
        company_id: destination_id
        for company_id, destination_id in company_rows
        if destination_id is not None
    }

    for destination_id in destinations.values():
        if destination_id not in company_ids:
            raise RuntimeError(
                f"Merged Company destination {destination_id} does not exist"
            )

    terminal_destinations: dict[UUID, UUID] = {}
    for source_id, direct_destination_id in destinations.items():
        visited = {source_id}
        terminal_id = direct_destination_id
        while terminal_id in destinations:
            if terminal_id in visited:
                raise RuntimeError(f"Company merge cycle includes {terminal_id}")
            visited.add(terminal_id)
            terminal_id = destinations[terminal_id]
        terminal_destinations[source_id] = terminal_id

    for source_id, terminal_id in terminal_destinations.items():
        if destinations[source_id] != terminal_id:
            Company.objects.filter(id=source_id).update(merged_into_id=terminal_id)
        merge_companies(source_id, terminal_id, staff)

    if Company.objects.filter(merged_into__merged_into__isnull=False).exists():
        raise RuntimeError("KAN-278 cleanup left a multi-hop Company merge")


def apply_reviewed_duplicate_cleanup() -> tuple[int, int]:
    """Apply the finite reviewed ledger and reject every unlisted residual."""
    if not REVIEWED_COMPANY_MERGES:
        return 0, 0
    production_sentinel = REVIEWED_COMPANY_MERGES[0]
    if not Company.objects.filter(name__in=production_sentinel.names).exists():
        return 0, 0

    # Resolve every human selector before touching data.  A changed production
    # snapshot therefore fails with no partial cleanup.
    company_groups = _resolve_company_decisions()
    person_groups = _resolve_person_decisions()
    invalid_links = _resolve_invalid_links()

    staff = Staff.get_automation_user()
    company_count = 0
    person_count = 0
    with transaction.atomic():
        for link in invalid_links:
            link.delete()
        _repair_matt_green()

        _flatten_existing_company_merges(staff)
        for canonical_company, source_companies in company_groups:
            for source_company in source_companies:
                merge_companies(source_company.id, canonical_company.id, staff)
                company_count += 1
        _flatten_existing_company_merges(staff)

        for canonical_person, source_people in person_groups:
            for source_person in source_people:
                merge_people(source_person.id, canonical_person.id, staff)
                person_count += 1

        _assert_residuals_are_defended()

    return company_count, person_count
