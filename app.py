from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from html import escape
from pathlib import Path

import streamlit as st
from access_control import set_actor, allowed, require, require_object, project_for, ROLES
from admin_ui import render_admin
from PIL import Image, ImageOps

from cost_export import build_cost_estimate
from drawings import annotated_image, drawings_pdf, import_drawing, report_drawings, show_drawing
from report_export import build_report, get_standard_texts
from report_import import parse_report, save_import
from storage import (
    DATA_DIR as USER_DATA_DIR,
    authenticate_user,
    change_password,
    create_complex,
    create_database_backup,
    create_project,
    create_report,
    database_status,
    delete_finding,
    get_user,
    init_db,
    insert_finding,
    list_complexes,
    list_drawings,
    list_findings,
    list_projects,
    list_reports,
    load_complex,
    load_project,
    load_report,
    register_user,
    save_report,
    update_complex,
    update_finding,
    update_project,
)
from unit_prices import load_unit_prices, parse_price_ids, price_label, suggest_price_ids, encode_price_links, resolve_price_links


APP_DIR = Path(__file__).resolve().parent
RESOURCE_DATA_DIR = APP_DIR / "data"
UPLOAD_DIR = USER_DATA_DIR / "uploads"
CHOICES_PATH = RESOURCE_DATA_DIR / "choices.json"
TEMPLATE_PATH = APP_DIR / "templates" / "rapportage_brandveiligheid_template.docx"
COST_TEMPLATE_PATH = APP_DIR / "templates" / "kostenraming_2026_template.xlsx"
UNIT_PRICES_PATH = RESOURCE_DATA_DIR / "eenheidsprijzen_2026.xlsx"
LOGO_PATH = APP_DIR / "assets" / "triacon-logo.png"
SESSION_TIMEOUT_SECONDS = 12 * 60 * 60

BUILDING_FIELDS = [
    ("bouwjaar", "Bouwjaar"),
    ("aantal_bouwlagen", "Aantal bouwlagen"),
    ("aantal_woningen", "Aantal woningen"),
    ("grondgebonden", "Grondgebonden"),
    ("portiek", "Portiek"),
    ("galerij", "Galerij"),
    ("corridor", "Corridor"),
    ("atrium", "Atrium"),
    ("lift", "Lift"),
]

INSTALLATION_FIELDS = [
    ("brandmeldinstallatie", "Brandmeld- en ontruimingsalarminstallatie"),
    ("overige_installaties", "Overige installaties aanwezig"),
    ("bouwjaar_installatie", "Bouwjaar installatie"),
    ("pve", "Programma van eisen (PVE)"),
    ("onderhoud_bmi_oai", "Onderhoudsrapportage BMI/OAI"),
    ("onderhoud_blusmiddelen", "Onderhoud gegevens blusmiddelen"),
    ("onderhoud_noodverlichting", "Onderhoud gegevens noodverlichting"),
    ("drukgeregelde_ventilatie", "Drukgeregelde ventilatie aanwezig"),
    ("zelfregelende_ventielen", "Zelfregelende ventilatieventielen aanwezig"),
]

ORGANISATION_FIELDS = [
    ("type_bezit", "Type bezit"),
    ("woonvorm", "Woonvorm"),
    ("zorgzwaarte", "Zorgzwaarte"),
    ("demarcatie", "Demarcatie"),
    ("melding_brandveilig_gebruik", "Melding brandveilig gebruik"),
    ("bhv", "Bedrijfshulpverlening (BHV)"),
    ("ontruimingsplan", "Bedrijfsnood-/ontruimingsplan"),
    ("ontruimingsplattegronden", "Ontruimingsplattegronden"),
]

MATERIAL_FIELDS = [
    ("bouwconstructie", "Bouwconstructie"),
    ("dakconstructie", "Dakconstructie"),
    ("dakisolatie", "Dakisolatie"),
    ("dakbedekking", "Dakbedekking"),
    ("gevels", "Gevels"),
    ("gevelisolatie", "Gevelisolatie"),
    ("scheidingswanden", "Scheidingswanden"),
    ("vloeren", "Vloeren"),
    ("vloerafwerking", "Vloerafwerking"),
    ("verlaagde_plafonds", "Verlaagde plafonds"),
    ("buitenkozijnen", "Buitenkozijnen"),
    ("binnenkozijnen", "Binnenkozijnen"),
    ("buitentrappen", "Buitentrappen"),
]

# Dropdown options for specific fields
FIELD_OPTIONS = {
    # Building fields - yes/no/n.a.
    "grondgebonden": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    "portiek": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    "galerij": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    "corridor": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    "atrium": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    "lift": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    
    # Installation fields
    "brandmeldinstallatie": ["Kies een item.", "BMI aanwezig", "OAI aanwezig", "BMI & OAI aanwezig", "Niet aanwezig, niet vereist", "Niet aanwezig, wel vereist", "N.v.t."],
    "pve": ["Kies een item.", "Aanwezig", "Niet aanwezig", "N.v.t."],
    "onderhoud_bmi_oai": ["Kies een item.", "Aanwezig", "Niet aanwezig", "N.v.t."],
    "onderhoud_blusmiddelen": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    "onderhoud_noodverlichting": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    "drukgeregelde_ventilatie": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    "zelfregelende_ventielen": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    
    # Organisation fields
    "type_bezit": ["Kies een item.", "Wooneenheden", "Maatschappelijk onroerend goed", "Bedrijf onroerend goed", "Gemengd", "N.v.t."],
    "woonvorm": ["Kies een item.", "Zelfstandig", "Zorg", "N.v.t."],
    "zorgzwaarte": ["Kies een item.", "Zorg op afspraak", "Zorg op afroep", "24-uurs zorg", "N.v.t."],
    "demarcatie": ["Kies een item.", "Ja", "Nee", "N.v.t."],
    "melding_brandveilig_gebruik": ["Kies een item.", "Aanwezig", "Niet aanwezig, niet vereist", "Niet aanwezig, wel vereist"],
    "bhv": ["Kies een item.", "Aanwezig", "Niet aanwezig, niet vereist", "Niet aanwezig, wel vereist"],
    "ontruimingsplan": ["Kies een item.", "Aanwezig", "Niet aanwezig, niet vereist", "Niet aanwezig, wel vereist"],
    "ontruimingsplattegronden": ["Kies een item.", "Aanwezig", "Niet aanwezig, niet vereist", "Niet aanwezig, wel vereist"],
    
    # Report data fields
    "tekeningen_ontvangen": ["Kies een item.", "wel", "geen"],
}


def load_choices() -> list[dict]:
    if not CHOICES_PATH.exists():
        return []
    return json.loads(CHOICES_PATH.read_text(encoding="utf-8"))


@st.cache_data
def unit_price_items() -> list[dict]:
    if not UNIT_PRICES_PATH.exists():
        return []
    return load_unit_prices(UNIT_PRICES_PATH)


@st.cache_data
def standard_report_texts() -> dict[str, str]:
    return get_standard_texts(TEMPLATE_PATH)


@st.cache_data
def logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def set_flash(message: str) -> None:
    st.session_state["flash_message"] = message


def show_flash() -> None:
    message = st.session_state.pop("flash_message", None)
    if message:
        st.toast(message, icon="✅")


def save_image(upload, project_id: int, prefix: str) -> str | None:
    require_object('edit_report', 'report', project_id)
    if upload is None:
        return None
    target_dir = UPLOAD_DIR / str(project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{prefix}-{uuid.uuid4().hex}.jpg"
    image = Image.open(upload)
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((1800, 1800))
    image.save(target, "JPEG", quality=86, optimize=True)
    return str(target.relative_to(USER_DATA_DIR))


def absolute_photo(relative: str | None) -> str | None:
    if not relative:
        return None
    path = Path(relative)
    if path.is_absolute():
        return str(path) if path.exists() else None
    normalized = Path(*path.parts[1:]) if path.parts and path.parts[0].lower() == "data" else path
    for candidate in (USER_DATA_DIR / normalized, APP_DIR / path, RESOURCE_DATA_DIR / normalized):
        if candidate.exists():
            return str(candidate)
    return None


def input_grid(data: dict, fields: list[tuple[str, str]], prefix: str) -> dict:
    result = {}
    cols = st.columns(2)
    for i, (key, label) in enumerate(fields):
        with cols[i % 2]:
            # Check if this field has predefined options
            if key in FIELD_OPTIONS:
                options = FIELD_OPTIONS[key]
                current_value = data.get(key, "")
                # If current value is not in options, default to first option
                try:
                    index = options.index(current_value) if current_value in options else 0
                except ValueError:
                    index = 0
                result[key] = editable_select(label, options, data.get(key), key=f"{prefix}_{key}")
            else:
                # Use text input for fields without predefined options
                result[key] = st.text_input(label, value=str(data.get(key, "")), key=f"{prefix}_{key}")
    return result


def session_user_id() -> int:
    return int(st.session_state["user_id"])


def render_auth_page() -> None:
    st.markdown(
        f"""
        <section class="auth-shell">
          <img src="{logo_data_uri()}" alt="TriaCon-logo">
          <h1>Brandveiligheidsinspectie</h1>
          <p>Log in om projecten, complexen en rapporten te beheren.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    login_tab, register_tab = st.tabs(["Inloggen", "Registreren"])
    with login_tab:
        with st.form("login_form"):
            email = st.text_input("E-mailadres", autocomplete="email")
            password = st.text_input("Wachtwoord", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Inloggen", type="primary", use_container_width=True)
            if submitted:
                user = authenticate_user(email, password)
                if user is None:
                    st.error("Inloggen niet gelukt. Controleer je gegevens en accountgoedkeuring. Na meerdere pogingen wordt inloggen tijdelijk geblokkeerd.")
                else:
                    st.session_state["user_id"] = int(user["id"])
                    st.session_state['auth_session_version'] = user['session_version']
                    set_flash(f"Welkom {user['name']}.")
                    st.rerun()
    with register_tab:
        with st.form("registration_form"):
            name = st.text_input("Naam", autocomplete="name")
            email = st.text_input("E-mailadres", autocomplete="email", key="register_email")
            password = st.text_input("Wachtwoord", type="password", autocomplete="new-password", key="register_password")
            confirm = st.text_input("Wachtwoord bevestigen", type="password", autocomplete="new-password")
            st.caption("Gebruik minimaal 10 tekens. Wachtwoorden worden uitsluitend gehasht opgeslagen.")
            submitted = st.form_submit_button("Account aanmaken", type="primary", use_container_width=True)
            if submitted:
                if password != confirm:
                    st.error("De wachtwoorden komen niet overeen.")
                else:
                    try:
                        user_id = register_user(name, email, password)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.success("Account aangevraagd. Een beheerder moet je account activeren en koppelen aan projecten voordat je kunt inloggen.")


def authenticated_user() -> dict | None:
    user_id = st.session_state.get("user_id")
    if not user_id:
        return None
    now = time.time()
    last_activity = float(st.session_state.get("auth_last_activity", now))
    if now - last_activity > SESSION_TIMEOUT_SECONDS:
        st.session_state.clear()
        st.warning("Uw sessie is verlopen. Log opnieuw in.")
        return None
    st.session_state["auth_last_activity"] = now
    user = get_user(int(user_id))
    if user is None or st.session_state.get('auth_session_version') != user['session_version']:
        st.session_state.clear()
        set_actor()
        return None
    set_actor(user['id'], user['session_version'])
    return user


def render_account_controls(user: dict) -> None:
    st.markdown(f"**{user['name']}**")
    st.caption(user["email"])
    st.caption(ROLES[user['role']])
    with st.expander("Account en wachtwoord"):
        with st.form("change_password_form"):
            current = st.text_input("Huidig wachtwoord", type="password")
            new = st.text_input("Nieuw wachtwoord", type="password")
            confirm = st.text_input("Nieuw wachtwoord bevestigen", type="password")
            if st.form_submit_button("Wachtwoord wijzigen", use_container_width=True):
                if new != confirm:
                    st.error("De nieuwe wachtwoorden komen niet overeen.")
                else:
                    try:
                        change_password(int(user["id"]), current, new)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state.clear()
                        set_actor()
                        st.success("Wachtwoord gewijzigd. Log opnieuw in.")
                        st.rerun()
    if allowed('backup'):
        render_backup_controls()
    if st.button("Uitloggen", use_container_width=True):
        st.session_state.clear()
        set_actor()
        st.rerun()


def render_backup_controls():
    require('backup')
    with st.expander("Dataopslag en back-up"):
        status = database_status()
        st.caption("Vaste database")
        st.code(status["path"], language=None)
        st.caption(
            f"{status['projects']} projecten · {status['complexes']} complexen · "
            f"{status['reports']} rapporten · databasecontrole: {status['integrity']}"
        )
        if st.button("Nieuwe databaseback-up maken", use_container_width=True):
            backup_path = create_database_backup()
            st.session_state["database_backup_bytes"] = backup_path.read_bytes()
            st.session_state["database_backup_name"] = backup_path.name
            st.success("Veilige databaseback-up aangemaakt.")
        if st.session_state.get("database_backup_bytes"):
            st.download_button(
                "Databaseback-up downloaden",
                data=st.session_state["database_backup_bytes"],
                file_name=st.session_state.get("database_backup_name", "brandveiligheid-backup.db"),
                mime="application/vnd.sqlite3",
                use_container_width=True,
            )


def editable_select(label, options, current=None, **kwargs):
    """Search, select or type; retain previously saved custom values."""
    options = list(options)
    if current and current not in options:
        options.append(current)
    return st.selectbox(label, options, index=options.index(current) if current in options else 0,
                        accept_new_options=True, **kwargs)


def render_word_import(complex_id, user):
    if not allowed('create_report', project_for('complex', complex_id)):
        return
    with st.expander("Bestaand Word-rapport inlezen"):
        st.caption("Importeer een TriaCon DOCX als nieuw, bewerkbaar rapport. Bestaande rapporten blijven ongewijzigd.")
        upload = st.file_uploader("Word-rapport", type=["docx"], key=f"word_import_{complex_id}")
        if upload is None:
            return
        content = upload.getvalue()
        try:
            parsed = parse_report(content)
        except Exception as exc:
            st.error(f"Rapport niet ingelezen: {exc}")
            return
        source = parsed['data']
        st.write(f"Broncomplex: {source.get('complexnummer', '')} · {source.get('complexnaam', '')}")
        st.write(f"{len(parsed['findings'])} bevindingen · {len(parsed['assets'])} afbeeldingen · {len(parsed['drawings'])} tekeningen")
        st.warning("Het rapport wordt gekoppeld aan het hierboven gekozen complex. Project-, opdrachtgever- en complexgegevens van dat complex zijn leidend bij volgende exports.")
        for warning in parsed['warnings']:
            st.caption(warning)
        if parsed['findings']:
            st.dataframe([{'Code': f"{f['code_group']}.{f['code_number']:02d}", 'Gebrek': f.get('gebrek', ''), 'Maatregel': f.get('maatregel', '')} for f in parsed['findings']], hide_index=True)
        title = st.text_input("Naam ingelezen rapport", value=Path(upload.name).stem, key=f"import_title_{complex_id}")
        import hashlib
        confirmed = st.checkbox("Ik heb de gegevens en het gekozen complex gecontroleerd", key=f"confirm_import_{complex_id}_{hashlib.sha256(content).hexdigest()}")
        if st.button("Rapport inlezen", type="primary", disabled=not confirmed, key=f"save_import_{complex_id}"):
            try:
                rid = save_import(parsed, content, int(complex_id), title, int(user['id']))
            except Exception as exc:
                st.error(f"Opslaan mislukt; er is geen rapport toegevoegd: {exc}")
                return
            st.session_state['selected_report_id'] = rid
            set_flash("Word-rapport ingelezen. Je kunt het nu wijzigen.")
            st.rerun()


def hierarchy_selector(user: dict) -> dict:
    projects = list_projects()
    with st.expander("Project, complex en rapport kiezen", expanded=not bool(projects)):
        project_column, complex_column, report_column = st.columns(3)
        with project_column:
            st.markdown("### 1. Project")
            with st.expander("＋ Nieuw project"):
                with st.form("new_project_form"):
                    name = st.text_input("Projectnaam")
                    client = st.text_input("Opdrachtgever")
                    number = st.text_input("Projectnummer")
                    description = st.text_area("Omschrijving")
                    if st.form_submit_button("Project aanmaken", type="primary", use_container_width=True, disabled=not allowed('create_project')):
                        try:
                            project_id = create_project(name, client, number, description, int(user["id"]))
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.session_state["selected_project_id"] = project_id
                            st.session_state.pop("selected_complex_id", None)
                            st.session_state.pop("selected_report_id", None)
                            set_flash("Project aangemaakt.")
                            st.rerun()
            if not projects:
                st.info("Er zijn nog geen projecten waartoe je toegang hebt. Een beheerder kan je aan een project koppelen.")
                return {}
            project_ids = [int(row["id"]) for row in projects]
            if st.session_state.get("selected_project_id") not in project_ids:
                st.session_state["selected_project_id"] = project_ids[0]
            selected_project_id = st.selectbox(
                "Bestaand project openen",
                project_ids,
                format_func=lambda value: next(row["name"] for row in projects if int(row["id"]) == value),
                key="selected_project_id",
            )
            project = load_project(int(selected_project_id))
        with complex_column:
            st.markdown("### 2. Complex")
            with st.expander("＋ Nieuw complex"):
                with st.form("new_complex_form"):
                    name = st.text_input("Complexnaam")
                    number = st.text_input("Complexnummer")
                    address = st.text_input("Adres")
                    postal_code = st.text_input("Postcode")
                    city = st.text_input("Plaats")
                    if st.form_submit_button("Complex aanmaken", type="primary", use_container_width=True, disabled=not allowed('create_complex', int(selected_project_id))):
                        try:
                            complex_id = create_complex(int(selected_project_id), name, number, address, postal_code, city, int(user["id"]))
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.session_state["selected_complex_id"] = complex_id
                            st.session_state.pop("selected_report_id", None)
                            set_flash("Complex aangemaakt.")
                            st.rerun()
            complexes = list_complexes(int(selected_project_id))
            if not complexes:
                st.info("Maak binnen dit project het eerste complex aan.")
                return {"project": project}
            complex_ids = [int(row["id"]) for row in complexes]
            if st.session_state.get("selected_complex_id") not in complex_ids:
                st.session_state["selected_complex_id"] = complex_ids[0]
            selected_complex_id = st.selectbox(
                "Bestaand complex openen",
                complex_ids,
                format_func=lambda value: next(
                    f"{row['complex_number'] or '—'} · {row['name']}" for row in complexes if int(row["id"]) == value
                ),
                key="selected_complex_id",
            )
            complex_data = load_complex(int(selected_complex_id))
        with report_column:
            st.markdown("### 3. Rapport")
            with st.expander("＋ Nieuw rapport"):
                with st.form("new_report_form"):
                    title = st.text_input("Rapportnaam", value="Rapportage brandveiligheid")
                    if st.form_submit_button("Rapport aanmaken", type="primary", use_container_width=True, disabled=not allowed('create_report', int(selected_project_id))):
                        report_id = create_report(int(selected_complex_id), title, int(user["id"]))
                        st.session_state["selected_report_id"] = report_id
                        set_flash("Rapport aangemaakt.")
                        st.rerun()
            render_word_import(selected_complex_id, user)
            reports = list_reports(int(selected_complex_id))
            if not reports:
                st.info("Maak binnen dit complex het eerste rapport aan.")
                return {"project": project, "complex": complex_data}
            report_ids = [int(row["id"]) for row in reports]
            if st.session_state.get("selected_report_id") not in report_ids:
                st.session_state["selected_report_id"] = report_ids[0]
            selected_report_id = st.selectbox(
                "Rapport openen",
                report_ids,
                format_func=lambda value: next(
                    f"{row['title']} · {row['status']}" for row in reports if int(row["id"]) == value
                ),
                key="selected_report_id",
            )
        st.caption("Alle inspecteurs werken in dezelfde centrale projectdatabase.")
    return {
        "project": project,
        "complex": complex_data,
        "report": load_report(int(selected_report_id)),
    }


def render_breadcrumbs(context: dict) -> None:
    parts = ["Projecten"]
    if context.get("project"):
        parts.append(context["project"]["name"])
    if context.get("complex"):
        parts.append(context["complex"]["name"])
    if context.get("report"):
        parts.append(context["report"]["title"])
    st.markdown(
        '<nav class="breadcrumbs">' + '<span>›</span>'.join(f"<strong>{escape(str(part))}</strong>" if index == len(parts) - 1 else escape(str(part)) for index, part in enumerate(parts)) + "</nav>",
        unsafe_allow_html=True,
    )


def render_hierarchy_data(context: dict) -> None:
    project = context["project"]
    complex_data = context["complex"]
    can_project = allowed('edit_project', project['id'])
    can_complex = allowed('edit_complex', project['id'])
    st.subheader("Project en complex")
    with st.form("project_data"):
        st.markdown("#### Project")
        p1, p2 = st.columns(2)
        project_name = p1.text_input("Projectnaam", project.get("name", ""), disabled=not can_project)
        client = p2.text_input("Opdrachtgever", project.get("client", ""), disabled=not can_project)
        project_number = p1.text_input("Projectnummer", project.get("project_number", ""), disabled=not can_project)
        description = st.text_area("Omschrijving", project.get("description", ""), disabled=not can_project)
        st.markdown("#### Complex")
        c1, c2 = st.columns(2)
        complex_name = c1.text_input("Complexnaam", complex_data.get("name", ""), disabled=not can_complex)
        complex_number = c2.text_input("Complexnummer", complex_data.get("complex_number", ""), disabled=not can_complex)
        address = c1.text_input("Adres", complex_data.get("address", ""), disabled=not can_complex)
        postal_code = c2.text_input("Postcode", complex_data.get("postal_code", ""), disabled=not can_complex)
        city = c2.text_input("Plaats", complex_data.get("city", ""), disabled=not can_complex)
        if st.form_submit_button("Project en complex opslaan", type="primary", disabled=not (can_project or can_complex)):
            if can_project:
                update_project(int(project["id"]), {
                "name": project_name, "client": client, "project_number": project_number, "description": description,
                })
            if can_complex:
                update_complex(int(complex_data["id"]), {
                "name": complex_name, "complex_number": complex_number, "address": address,
                "postal_code": postal_code, "city": city,
                })
            set_flash("Project- en complexgegevens opgeslagen.")
            st.rerun()


def render_report_data(project: dict) -> None:
    st.subheader("Rapportgegevens")
    with st.form("report_data"):
        c1, c2 = st.columns(2)
        with c1:
            title = st.text_input("Rapportnaam", project.get("title", ""))
            kenmerk = st.text_input("Kenmerk", project.get("kenmerk", ""))
            st.text_input("Complex", f"{project.get('complexnummer','')} · {project.get('complexnaam','')}", disabled=True)
            st.text_input("Project", project.get("projectnaam", ""), disabled=True)
        with c2:
            opdrachtgever_adres = st.text_area("Adres opdrachtgever", project.get("opdrachtgever_adres", ""), height=70)
            opdrachtgever_contact = st.text_input("Contactpersoon opdrachtgever", project.get("opdrachtgever_contact", ""))
            inspecteur = st.text_input("Inspecteur(s)", project.get("inspecteur", ""))
            gecontroleerd = st.text_input("Gecontroleerd door", project.get("gecontroleerd", ""))
            triacon_contact = st.text_input("Contactpersoon TriaCon", project.get("triacon_contact", ""))
            triacon_email = st.text_input("E-mail TriaCon", project.get("triacon_email", ""))
        c3, c4, c5 = st.columns(3)
        report_date = c3.text_input("Rapportdatum", project.get("report_date", ""))
        version = c4.text_input("Versie", project.get("version", "0.1"))
        with c5:
            status = editable_select("Status", ["Concept", "Ter controle", "Definitief"], project.get("status", "Concept"))
        if st.form_submit_button("Rapportgegevens opslaan", type="primary"):
            project.update({
                "title": title, "kenmerk": kenmerk,
                "opdrachtgever_adres": opdrachtgever_adres,
                "opdrachtgever_contact": opdrachtgever_contact, "inspecteur": inspecteur,
                "gecontroleerd": gecontroleerd, "triacon_contact": triacon_contact,
                "triacon_email": triacon_email, "report_date": report_date,
                "version": version, "status": status,
            })
            save_report(project["id"], project, session_user_id())
            st.success("Rapportgegevens opgeslagen.")


def render_general_data(project: dict) -> None:
    st.subheader("Algemene gegevens")
    with st.form("general_data"):
        algemene_omschrijving = st.text_area("Algemene omschrijving complex", project.get("algemene_omschrijving", ""), height=130)
        st.markdown("#### Gebouwgegevens")
        building = input_grid(project, BUILDING_FIELDS, "building")
        st.markdown("#### Installatietechnische gegevens")
        installation = input_grid(project, INSTALLATION_FIELDS, "installation")
        st.markdown("#### Organisatorische gegevens")
        organisation = input_grid(project, ORGANISATION_FIELDS, "organisation")
        st.markdown("#### Materialenlijst")
        materials = input_grid(project, MATERIAL_FIELDS, "materials")
        texts = standard_report_texts()
        st.markdown("#### Vaste rapportteksten")
        st.caption("Deze teksten komen rechtstreeks uit de Word-template en zijn hier bewust niet vrij bewerkbaar.")
        st.text_area("3.6 Doelstelling van het onderzoek", texts["doelstelling"], height=100, disabled=True)
        
        # Dynamic ausgangspunten with tekeningen option
        tekeningen_options = ["Kies een item.", "wel", "geen"]
        tekeningen_value = project.get("tekeningen_ontvangen", "geen")
        tekeningen_index = tekeningen_options.index(tekeningen_value) if tekeningen_value in tekeningen_options else 2  # Default to "geen"
        tekeningen_ontvangen = editable_select("Tekeningen ontvangen", tekeningen_options, tekeningen_value, key="tekeningen_ontvangen_select")
        
        uitgangspunten_preview = texts["uitgangspunten"]
        if tekeningen_ontvangen in {"wel", "geen"}:
            uitgangspunten_preview = uitgangspunten_preview.replace(
                "zijn geen tekeningen",
                f"zijn {tekeningen_ontvangen} tekeningen",
                1,
            )
        st.text_area("3.7 Uitgangspunten", uitgangspunten_preview, height=150, disabled=True)
        
        bezochte_woningen = st.text_area("Bezochte woningen", project.get("bezochte_woningen", ""), height=80)
        beperkingen = st.text_area("Beperkingen", project.get("beperkingen", ""), height=80)
        if st.form_submit_button("Algemene gegevens opslaan", type="primary"):
            project.update({"algemene_omschrijving": algemene_omschrijving, "bezochte_woningen": bezochte_woningen, "beperkingen": beperkingen, "tekeningen_ontvangen": tekeningen_ontvangen})
            project.update(building)
            project.update(installation)
            project.update(organisation)
            project.update(materials)
            save_report(project["id"], project, session_user_id())
            st.success("Algemene gegevens opgeslagen.")


def render_situation(project: dict) -> None:
    st.subheader("Situatie- en complexfoto’s")
    st.caption("Op een iPad kan ‘Maak foto’ de camera openen. Bestaande JPG- of PNG-bestanden kunnen ook worden gekozen.")
    slots = [("voorgevel", "Voorgevel"), ("kopgevel", "Kopgevel"), ("achtergevel", "Achtergevel"), ("luchtfoto", "Luchtfoto / situatietekening")]
    with st.form("situation_photos"):
        uploads = {}
        cols = st.columns(2)
        for i, (key, label) in enumerate(slots):
            with cols[i % 2]:
                current = absolute_photo(project.get(f"photo_{key}"))
                if current:
                    st.image(current, caption=label, use_container_width=True)
                uploads[key] = st.file_uploader(label, type=["jpg", "jpeg", "png"], key=f"situation_{key}")
        if st.form_submit_button("Situatiefoto’s opslaan", type="primary"):
            for key, upload in uploads.items():
                path = save_image(upload, project["id"], key)
                if path:
                    project[f"photo_{key}"] = path
            save_report(project["id"], project, session_user_id())
            st.success("Situatiefoto’s opgeslagen.")


def merge_defects(selected_choices: list[dict]) -> dict:
    """Merge multiple defects, consolidating identical requirements/measures."""
    if not selected_choices:
        return {}
    
    if len(selected_choices) == 1:
        return selected_choices[0]
    
    # Collect unique subjects
    subjects = list(dict.fromkeys(c.get("onderwerp", "") for c in selected_choices if c.get("onderwerp")))
    
    # Merge requirements (artikelen)
    artikelen = [c.get("artikel", "") for c in selected_choices if c.get("artikel")]
    unique_artikelen = list(dict.fromkeys(artikelen))
    
    # Merge measures (maatregelen)
    maatregelen = [c.get("maatregel", "") for c in selected_choices if c.get("maatregel")]
    unique_maatregelen = list(dict.fromkeys(maatregelen))
    
    # Merge remarks and guidelines (keep all unique)
    remarks = [c.get("opmerking", "") for c in selected_choices if c.get("opmerking")]
    unique_remarks = list(dict.fromkeys(remarks))
    guidelines = [c.get("richtlijn", "") for c in selected_choices if c.get("richtlijn")]
    unique_guidelines = list(dict.fromkeys(guidelines))
    
    # Collect all defect descriptions
    defects = [c.get("gebrek", "") for c in selected_choices if c.get("gebrek")]
    
    # Build merged result
    merged = {
        "onderwerp": " / ".join(subjects),
        "gebrek": "\n\n".join(defects),
        "artikel": "\n\n".join(unique_artikelen) if len(unique_artikelen) > 1 else (unique_artikelen[0] if unique_artikelen else ""),
        "maatregel": "\n\n".join(unique_maatregelen) if len(unique_maatregelen) > 1 else (unique_maatregelen[0] if unique_maatregelen else ""),
        "opmerking": "\n\n".join(unique_remarks) if unique_remarks else "",
        "richtlijn": "\n\n".join(unique_guidelines) if unique_guidelines else "",
    }
    
    return merged


def render_add_finding(project: dict, choices: list[dict]) -> None:
    st.subheader("Nieuwe bevinding")
    location = st.session_state.get("drawing_location")
    if location and location.get("report_id") != project["id"]:
        location = None
    if location:
        st.info(f"Nieuwe bevinding op tekening {location['number']} · pagina {location['page']}.")
        if st.button("Annuleren en terug naar tekening"):
            st.session_state.pop("drawing_location", None)
            st.session_state["navigate_to"] = "Tekeningen"
            st.rerun()
    finding_type = st.radio("Soort registratie", ["Maatregel", "Overige bevinding"], horizontal=True)

    # st.multiselect is deliberately used as a searchable combobox. Streamlit
    # renders the search input inside the opened dropdown, which keeps the long
    # standard-defect list out of the page and works well with iPad touch input.
    entry_key = location["event_id"] if location else str(st.session_state.get("finding_entry_generation", 0))
    select_key = f"standard_defects_{project['id']}_{entry_key}"
    labels = ["Vrij invoeren"]
    label_to_choice = {}
    duplicate_count = {}
    for choice in choices:
        base_label = f"{choice.get('onderwerp', 'Onbekend onderwerp')} — {choice.get('gebrek', '')}"
        duplicate_count[base_label] = duplicate_count.get(base_label, 0) + 1
        label = base_label
        if duplicate_count[base_label] > 1:
            label = f"{base_label} ({duplicate_count[base_label]})"
        labels.append(label)
        label_to_choice[label] = choice

    selected_labels = st.multiselect(
        "Standaard gebreken zoeken en selecteren",
        labels,
        accept_new_options=True,
        key=select_key,
        placeholder="Klik hier en typ om te zoeken…",
        help="Typ om te zoeken of voer een eigen gebrek in en druk op Enter. Meerdere gebreken selecteren blijft mogelijk.",
    )
    selected_choices = [label_to_choice.get(label, {"gebrek": label, "onderwerp": "", "artikel": "", "maatregel": ""}) for label in selected_labels if label != "Vrij invoeren"]
    
    # Merge selected defects
    merged_choice = merge_defects(selected_choices)
    
    # Show merged information
    if merged_choice:
        eis_preview = merged_choice.get("artikel", "")
        maatregel_preview = merged_choice.get("maatregel", "")
        if len(eis_preview) > 200:
            eis_preview = eis_preview[:200] + "…"
        if len(maatregel_preview) > 200:
            maatregel_preview = maatregel_preview[:200] + "…"
        st.info(f"BBL/eis:\n{eis_preview}\n\nMaatregel:\n{maatregel_preview}")

    choice_key = uuid.uuid5(uuid.NAMESPACE_URL, f"{project['id']}:{entry_key}:" + "\x1f".join(selected_labels)).hex[:12]
    prices = unit_price_items()
    prices_by_id = {int(item["id"]): item for item in prices}
    suggested_cost_items = []
    for selected_choice in selected_choices:
        for price_id in suggest_price_ids(selected_choice.get("maatregel", ""), prices):
            if price_id not in suggested_cost_items:
                suggested_cost_items.append(price_id)
    with st.form(f"add_finding_{project['id']}_{entry_key}", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            code_group = editable_select("Codegroep", ["G", "W"], help="G = gemeenschappelijke ruimte, W = woning")
        with c2:
            discipline = editable_select("Werksoort", ["Bouwkundig", "Installatietechnisch", "Organisatorisch"])
        onderwerp = c3.text_input("Onderwerp", value=merged_choice.get("onderwerp", ""), key=f"new_subject_{choice_key}")
        c4, c5, c6 = st.columns(3)
        tekeningnummer = c4.text_input("Tekeningnummer", location["number"] if location else "N.v.t.")
        bouwlaag = c5.text_input("Bouwlaag", location["floor"] if location else "")
        ruimte = c6.text_input("Ruimte(nummer)")
        eis = st.text_area("Eis / artikel BBL", value=merged_choice.get("artikel", ""), height=90, key=f"new_requirement_{choice_key}")
        gebrek = st.text_area("Gebrek / bevinding", value=merged_choice.get("gebrek", ""), height=100, key=f"new_defect_{choice_key}")
        c7, c8 = st.columns(2)
        aantal = c7.text_input("Aantal")
        afmeting = c8.text_input("Afmeting")
        maatregel_label = "Conclusie / advies" if finding_type == "Overige bevinding" else "Maatregel"
        maatregel = st.text_area(maatregel_label, value=merged_choice.get("maatregel", ""), height=110, key=f"new_measure_{choice_key}")
        st.markdown("#### Kostenraming")
        cost_items = st.multiselect(
            "Gekoppelde eenheidsprijzen",
            options=list(prices_by_id),
            default=[price_id for price_id in suggested_cost_items if price_id in prices_by_id],
            format_func=lambda price_id: price_label(prices_by_id[price_id]),
            key=f"new_cost_items_{choice_key}",
            help="De app stelt prijsregels voor op basis van de standaardmaatregel. Controleer of pas de selectie aan.",
        )
        st.caption("De hoeveelheid komt uit Aantal. Wijzig je de maatregel zonder de prijsselectie aan te passen, dan wordt de koppeling opnieuw bepaald bij opslaan. Onzekere koppelingen moet je handmatig aanvullen; ze worden niet als € 0 meegerekend.")
        opmerking = st.text_area("Opmerking", value=merged_choice.get("opmerking", ""), height=80, key=f"new_note_{choice_key}")
        richtlijn = st.text_area("Richtlijn", value=merged_choice.get("richtlijn", ""), height=70, key=f"new_guideline_{choice_key}")
        st.markdown("#### Foto’s")
        
        p1, p2 = st.columns(2)
        
        with p1:
            st.write("**Inspectiefoto (voor)**")
            photo_camera = st.camera_input("Maak inspectiefoto met camera")
            photo_upload = st.file_uploader(
                "Of kies een bestaande inspectiefoto",
                type=["jpg", "jpeg", "png"],
                key="new_before_upload",
            )
        
        with p2:
            st.write("**Herstel foto (optioneel)**")
            photo_after = st.file_uploader("Foto na herstel", type=["jpg", "jpeg", "png"], key="new_after_upload")
        submitted = st.form_submit_button("Bevinding toevoegen", type="primary")
        if submitted:
            if not gebrek.strip():
                st.error("Vul een gebrek of bevinding in.")
            else:
                before_path = save_image(photo_camera or photo_upload, project["id"], "inspectie")
                after_path = save_image(photo_after, project["id"], "herstel")
                insert_finding(project["id"], {
                    "finding_type": finding_type,
                    "code_group": code_group,
                    "discipline": discipline,
                    "onderwerp": onderwerp,
                    "tekeningnummer": tekeningnummer,
                    "bouwlaag": bouwlaag,
                    "ruimte": ruimte,
                    "eis": eis,
                    "gebrek": gebrek,
                    "aantal": aantal,
                    "afmeting": afmeting,
                    "maatregel": maatregel,
                    "opmerking": opmerking,
                    "richtlijn": richtlijn,
                    "cost_items": encode_price_links(cost_items, maatregel, prices, merged_choice.get('maatregel', ''), suggested_cost_items),
                    "photo_before": before_path or "",
                    "photo_after": after_path or "",
                    "drawing_location": location,
                }, session_user_id())
                st.session_state.pop("drawing_location", None)
                st.session_state["finding_entry_generation"] = st.session_state.get("finding_entry_generation", 0) + 1
                st.session_state.pop("report_bytes", None)
                st.session_state.pop("cost_estimate_bytes", None)
                if location:
                    st.session_state["navigate_to"] = "Tekeningen"
                    st.session_state["drawing_view_generation"] = st.session_state.get("drawing_view_generation", 0) + 1
                set_flash("Bevinding succesvol toegevoegd.")
                st.rerun()


def render_drawings(project: dict) -> None:
    st.subheader("Tekeningen")
    st.caption("Tik een plek aan om een bevinding te maken. Na opslaan verschijnt de rode gebrekscode op de tekening.")
    with st.expander("Tekening inladen"):
        generation = st.session_state.get("drawing_upload_generation", 0)
        with st.form(f"drawing_upload_{project['id']}_{generation}"):
            upload = st.file_uploader("Tekening (PDF, PNG of JPG)", type=["pdf", "png", "jpg", "jpeg"], max_upload_size=40)
            number = st.text_input("Tekeningnummer / naam")
            floor = st.text_input("Bouwlaag van de tekening")
            if st.form_submit_button("Tekening opslaan", type="primary", disabled=not allowed('edit_report', project['project_id'])):
                if upload is None:
                    st.error("Kies eerst een tekening.")
                else:
                    try:
                        with st.spinner("Tekening wordt verwerkt…"):
                            ids = import_drawing(upload.getvalue(), upload.name, project["id"], number, floor)
                    except Exception as exc:
                        st.error(f"De tekening kon niet worden ingeladen: {exc}")
                    else:
                        st.session_state[f"selected_drawing_{project['id']}"] = ids[0]
                        st.session_state["drawing_upload_generation"] = generation + 1
                        st.session_state.pop("report_bytes", None)
                        set_flash(f"Tekening opgeslagen ({len(ids)} pagina’s).")
                        st.rerun()
    drawings = list_drawings(project["id"])
    if not drawings:
        st.info("Laad een tekening in om gebreken op een plattegrond vast te leggen.")
        return
    by_id = {item["id"]: item for item in drawings}
    drawing_id = st.selectbox("Tekening / pagina", list(by_id), key=f"selected_drawing_{project['id']}",
                             format_func=lambda key: f"{by_id[key]['drawing_number']} · pagina {by_id[key]['page_number']} · {by_id[key]['floor']}")
    drawing = by_id[drawing_id]
    if allowed('export', project['project_id']):
        render_drawing_downloads(drawings, drawing, project)
    generation = st.session_state.get("drawing_view_generation", 0)
    event = show_drawing(drawing, key=f"drawing_view_{project['id']}_{drawing_id}_{generation}")
    if allowed('edit_report', project['project_id']) and event and event.get("event_id") != st.session_state.get("last_drawing_event"):
        st.session_state["last_drawing_event"] = event.get("event_id")
        try:
            x, y = float(event["x"]), float(event["y"])
            if event.get("drawing_id") != drawing_id or not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError("Ongeldige plek op de tekening.")
        except (KeyError, TypeError, ValueError):
            st.error("Tik opnieuw op een plek binnen de tekening.")
            return
        st.session_state["drawing_location"] = dict(
            report_id=project["id"], drawing_id=drawing_id, x=x, y=y, event_id=event["event_id"],
            number=drawing["drawing_number"], floor=drawing["floor"], page=drawing["page_number"],
        )
        st.session_state["navigate_to"] = "Inspectie"
        st.rerun()


def render_drawing_downloads(drawings, drawing, project):
    require('export', project['project_id'])
    drawing_id = drawing['id']
    with st.expander("Bijgewerkte tekeningen downloaden"):
        st.caption("Inclusief alle opgeslagen rode gebrekscodes. De originele bestanden blijven bewaard. PDF-downloads zijn gerasteriseerd.")
        c1, c2 = st.columns(2)
        c1.download_button("Deze pagina downloaden (PNG)", annotated_image(drawing).getvalue(),
                           file_name=f"tekening-{drawing_id}-bijgewerkt.png", mime="image/png",
                           on_click="ignore", use_container_width=True)
        c2.download_button("Deze pagina downloaden (PDF)", drawings_pdf([drawing]),
                           file_name=f"tekening-{drawing_id}-bijgewerkt.pdf", mime="application/pdf",
                           on_click="ignore", use_container_width=True)
        if st.button("Alle tekeningen klaarzetten als PDF", key=f"prepare_drawings_{project['id']}"):
            with st.spinner("Tekeningen met actuele gebrekscodes samenvoegen…"):
                pdf = drawings_pdf(drawings)
            st.download_button("Alle tekeningen downloaden (PDF)", pdf,
                               file_name=f"rapport-{project['id']}-tekeningen-bijgewerkt.pdf",
                               mime="application/pdf", on_click="ignore", use_container_width=True)


def render_findings(project: dict) -> None:
    findings = list_findings(project["id"])
    prices = unit_price_items()
    prices_by_id = {int(item["id"]): item for item in prices}
    st.subheader(f"Opgeslagen bevindingen ({len(findings)})")
    if not findings:
        st.info("Nog geen bevindingen toegevoegd.")
        return
    for finding in findings:
        resolved_prices, missing_links = resolve_price_links(finding, prices)
        stored_cost_items = [int(p['id']) for p in resolved_prices]
        # A deliberately empty selection must stay empty when reopening.
        suggested_cost_items = stored_cost_items if finding.get("cost_items") not in (None, '', '[]') else suggest_price_ids(finding.get("maatregel", ""), prices)
        code = f"{finding['code_group']}.{int(finding['code_number']):02d}"
        with st.expander(f"{code} · {finding['discipline']} · {finding['gebrek'][:90]}"):
            c1, c2 = st.columns([1, 2])
            with c1:
                if absolute_photo(finding.get("photo_before")):
                    st.image(absolute_photo(finding["photo_before"]), caption="Inspectie", use_container_width=True)
                if absolute_photo(finding.get("photo_after")):
                    st.image(absolute_photo(finding["photo_after"]), caption="Na herstel", use_container_width=True)
            with c2:
                st.write(f"**Locatie:** {finding.get('bouwlaag','')} · {finding.get('ruimte','')}")
                st.write(f"**Eis:** {finding.get('eis','')}")
                st.write(f"**Aantal / afmeting:** {finding.get('aantal','')} · {finding.get('afmeting','')}")
                st.write(f"**Maatregel:** {finding.get('maatregel','')}")
                if suggested_cost_items:
                    st.write("**Kostenregels:** " + "; ".join(prices_by_id[price_id]["description"] for price_id in suggested_cost_items if price_id in prices_by_id))
                else:
                    st.write("**Kostenregels:** nog niet gekoppeld")
                if missing_links and finding.get('finding_type') == 'Maatregel':
                    st.warning("Controleer de prijskoppeling: " + "; ".join(missing_links))
                if finding.get("opmerking"):
                    st.write(f"**Opmerking:** {finding['opmerking']}")
            if not allowed('edit_report', project['project_id']):
                if allowed('delete_finding', project['project_id']) and st.button('Bevinding verwijderen', key=f"readonly_delete_{finding['id']}"):
                    delete_finding(finding['id'])
                    st.rerun()
                continue
            st.markdown("#### Bewerken")
            with st.form(f"edit_finding_{finding['id']}"):
                e1, e2, e3 = st.columns(3)
                finding_type = e1.selectbox(
                    "Soort registratie", ["Maatregel", "Overige bevinding"],
                    index=["Maatregel", "Overige bevinding"].index(finding.get("finding_type", "Maatregel")),
                    key=f"edit_type_{finding['id']}",
                )
                with e2:
                    code_group = editable_select("Codegroep", ["G", "W"], finding.get("code_group", "G"), key=f"edit_group_{finding['id']}")
                code_number = e3.number_input("Volgnummer", min_value=1, value=int(finding.get("code_number") or 1), step=1, key=f"edit_number_{finding['id']}")
                discipline = editable_select(
                    "Werksoort", ["Bouwkundig", "Installatietechnisch", "Organisatorisch"],
                    current=finding.get("discipline", "Bouwkundig"),
                    key=f"edit_discipline_{finding['id']}",
                )
                onderwerp = st.text_input("Onderwerp", finding.get("onderwerp", ""), key=f"edit_subject_{finding['id']}")
                e4, e5, e6 = st.columns(3)
                tekeningnummer = e4.text_input("Tekeningnummer", finding.get("tekeningnummer", ""), key=f"edit_drawing_{finding['id']}")
                bouwlaag = e5.text_input("Bouwlaag", finding.get("bouwlaag", ""), key=f"edit_floor_{finding['id']}")
                ruimte = e6.text_input("Ruimte(nummer)", finding.get("ruimte", ""), key=f"edit_room_{finding['id']}")
                eis = st.text_area("Eis / artikel BBL", finding.get("eis", ""), key=f"edit_req_{finding['id']}")
                gebrek = st.text_area("Gebrek / bevinding", finding.get("gebrek", ""), key=f"edit_defect_{finding['id']}")
                e7, e8 = st.columns(2)
                aantal = e7.text_input("Aantal", finding.get("aantal", ""), key=f"edit_count_{finding['id']}")
                afmeting = e8.text_input("Afmeting", finding.get("afmeting", ""), key=f"edit_size_{finding['id']}")
                maatregel = st.text_area("Maatregel / advies", finding.get("maatregel", ""), key=f"edit_measure_{finding['id']}")
                cost_items = st.multiselect(
                    "Gekoppelde eenheidsprijzen",
                    options=list(prices_by_id),
                    default=[price_id for price_id in suggested_cost_items if price_id in prices_by_id],
                    format_func=lambda price_id: price_label(prices_by_id[price_id]),
                    key=f"edit_cost_items_{finding['id']}",
                    help="Controleer de koppeling of kies handmatig prijsregels. Wijzig je alleen de maatregel, dan wordt de koppeling bij opslaan opnieuw bepaald.",
                )
                opmerking = st.text_area("Opmerking", finding.get("opmerking", ""), key=f"edit_note_{finding['id']}")
                richtlijn = st.text_area("Richtlijn", finding.get("richtlijn", ""), key=f"edit_guide_{finding['id']}")
                u1, u2 = st.columns(2)
                new_before = u1.file_uploader("Inspectiefoto vervangen", type=["jpg", "jpeg", "png"], key=f"edit_before_{finding['id']}")
                new_after = u2.file_uploader("Herstelfoto vervangen", type=["jpg", "jpeg", "png"], key=f"edit_after_{finding['id']}")
                save_edit = st.form_submit_button("Wijzigingen opslaan", type="primary")
                if save_edit:
                    before_path = save_image(new_before, project["id"], "inspectie") or finding.get("photo_before", "")
                    after_path = save_image(new_after, project["id"], "herstel") or finding.get("photo_after", "")
                    update_finding(finding["id"], {
                        "finding_type": finding_type, "code_group": code_group, "code_number": code_number,
                        "discipline": discipline, "onderwerp": onderwerp, "tekeningnummer": tekeningnummer,
                        "bouwlaag": bouwlaag, "ruimte": ruimte, "eis": eis, "gebrek": gebrek,
                        "aantal": aantal, "afmeting": afmeting, "maatregel": maatregel,
                        "opmerking": opmerking, "richtlijn": richtlijn, "cost_items": encode_price_links(cost_items, maatregel, prices, finding.get('maatregel', ''), suggested_cost_items),
                        "photo_before": before_path, "photo_after": after_path,
                    }, session_user_id())
                    st.session_state.pop("report_bytes", None)
                    st.session_state.pop("cost_estimate_bytes", None)
                    st.success("Bevinding bijgewerkt.")
                    st.rerun()
            if st.button("Bevinding verwijderen", key=f"delete_{finding['id']}", disabled=not allowed('delete_finding', project['project_id'])):
                delete_finding(finding["id"])
                st.session_state.pop("report_bytes", None)
                st.session_state.pop("cost_estimate_bytes", None)
                st.rerun()


def render_report(project: dict) -> None:
    st.subheader("Rapport afronden en exporteren")
    with st.form("report_texts"):
        samenvatting = st.text_area("Samenvatting", project.get("samenvatting", ""), height=190)
        conclusie = st.text_area("Conclusie", project.get("conclusie", ""), height=190)
        gelijkwaardigheid = st.text_area("Gelijkwaardigheidsoplossing", project.get("gelijkwaardigheid", ""), height=100)
        if st.form_submit_button("Rapportteksten opslaan", type="primary", disabled=not allowed('edit_report', project['project_id'])):
            project.update({"samenvatting": samenvatting, "conclusie": conclusie, "gelijkwaardigheid": gelijkwaardigheid})
            save_report(project["id"], project, session_user_id())
            st.success("Rapportteksten opgeslagen.")
    if not allowed('export', project['project_id']):
        st.info('Je hebt voor dit project geen exportrechten.')
        return
    findings = list_findings(project["id"])
    export_signature = hashlib.sha256(json.dumps(["export-20260924", project, findings], sort_keys=True, default=str).encode()).hexdigest()
    if st.session_state.get('export_signature') != export_signature:
        st.session_state.pop('report_bytes', None)
        st.session_state.pop('cost_estimate_bytes', None)
        st.session_state['export_signature'] = export_signature
    missing = []
    for key, label in [("complexnummer", "complexnummer"), ("complexnaam", "complexnaam"), ("projectadres", "projectadres"), ("inspecteur", "inspecteur")]:
        if not project.get(key):
            missing.append(label)
    if missing:
        st.warning("Nog niet ingevuld: " + ", ".join(missing))
    st.metric("Bevindingen in rapport", len(findings))
    word_column, cost_column = st.columns(2)
    with word_column:
        st.markdown("### Word-rapport")
        if not TEMPLATE_PATH.exists():
            st.error("De Word-template ontbreekt in de appmap.")
        else:
            if st.button("Word-rapport voorbereiden", type="primary", use_container_width=True):
                with st.spinner("Rapport wordt opgebouwd…"):
                    payload = dict(project)
                    for key in ["photo_voorgevel", "photo_kopgevel", "photo_achtergevel", "photo_luchtfoto"]:
                        payload[key] = absolute_photo(project.get(key))
                    for finding in findings:
                        finding["photo_before"] = absolute_photo(finding.get("photo_before"))
                        finding["photo_after"] = absolute_photo(finding.get("photo_after"))
                    st.session_state.pop("report_bytes", None)
                    try:
                        content = build_report(TEMPLATE_PATH, payload, findings, drawings=report_drawings(project["id"]))
                    except Exception as exc:
                        st.error(f"Het Word-rapport kon niet veilig worden gemaakt: {exc}. De opgeslagen inspectiegegevens blijven behouden.")
                    else:
                        st.session_state.report_bytes = content
                        st.session_state.report_name = f"{project.get('kenmerk') or 'concept'} Rapportage brandveiligheid {project.get('complexnaam') or ''}.docx".strip()
            if st.session_state.get("report_bytes"):
                st.download_button(
                    "Download Word-rapport",
                    data=st.session_state.report_bytes,
                    file_name=st.session_state.get("report_name", "rapportage_brandveiligheid.docx"),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary",
                    use_container_width=True,
                )
                st.caption("Open het document in Microsoft Word en werk de inhoudsopgave bij met Ctrl+A en F9.")

    with cost_column:
        st.markdown("### Kostenraming Excel")
        if not COST_TEMPLATE_PATH.exists() or not UNIT_PRICES_PATH.exists():
            st.error("De kostenraming-template of eenheidsprijzenlijst ontbreekt in de appmap.")
        else:
            if st.button("Kostenraming voorbereiden", type="primary", use_container_width=True):
                with st.spinner("Kostenraming wordt opgebouwd…"):
                    content, unresolved = build_cost_estimate(COST_TEMPLATE_PATH, UNIT_PRICES_PATH, dict(project), findings)
                    st.session_state.cost_estimate_bytes = content
                    st.session_state.cost_estimate_unresolved = unresolved
                    st.session_state.cost_estimate_name = f"{project.get('kenmerk') or 'concept'} Kostenraming brandveiligheid {project.get('complexnaam') or ''}.xlsx".strip()
            if st.session_state.get("cost_estimate_bytes"):
                st.download_button(
                    "Download kostenraming Excel",
                    data=st.session_state.cost_estimate_bytes,
                    file_name=st.session_state.get("cost_estimate_name", "kostenraming_brandveiligheid.xlsx"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                )
                unresolved = int(st.session_state.get("cost_estimate_unresolved") or 0)
                if unresolved:
                    st.warning(f"{unresolved} kostenregel(s) vereisen controle: een ontbrekende koppeling geeft #N/B in Excel; een bronprijs van € 0 blijft € 0. Vul deze regels aan voordat je het totaal gebruikt.")
                else:
                    st.caption("Alle kostenregels zijn gekoppeld aan de eenheidsprijzenlijst 2026.")


def render_dashboard(context: dict) -> None:
    project = context.get("project")
    complex_data = context.get("complex")
    report = context.get("report")
    findings = list_findings(report["id"]) if report else []
    projects = list_projects()
    measures = sum(f.get("finding_type") == "Maatregel" for f in findings)
    other = len(findings) - measures
    photos = sum(bool(f.get("photo_before")) + bool(f.get("photo_after")) for f in findings)
    title = report.get("title") if report else (complex_data.get("name") if complex_data else (project.get("name") if project else "Projectomgeving"))
    subtitle = (
        f"{report.get('complexnummer') or 'Nog geen complexnummer'} · {report.get('status') or 'Concept'}"
        if report else "Kies hierboven een project, complex en rapport."
    )
    st.markdown(
        f"""
        <section class="dashboard-hero">
          <div class="eyebrow">Jouw inspectieomgeving</div><h2>{escape(str(title))}</h2>
          <p>{escape(str(subtitle))}</p>
          <span class="hero-status">{escape(str(report.get('status') or 'Concept')) if report else 'Projecten & rapporten'}</span>
        </section>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="overview_metrics"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Projecten", len(projects))
        c2.metric("Complexen", sum(int(item["complex_count"]) for item in projects))
        c3.metric("Rapporten", sum(int(item["report_count"]) for item in projects))
        c4.metric("Bevindingen in dit rapport", len(findings))
    if report:
        st.markdown("### Verder met je inspectie")
        with st.container(key="quick_actions"):
            actions = [
                ("＋", "Bevinding vastleggen", "Voeg foto's, een gebrek en een maatregel toe.", "Nieuwe bevinding", "Inspectie"),
                ("⌖", "Werken op tekening", "Koppel gebreken aan een plek op de plattegrond.", "Tekeningen openen", "Tekeningen"),
                ("↗", "Rapport afronden", "Werk de teksten bij en exporteer Word of Excel.", "Naar rapport", "Rapport"),
            ]
            for column, (icon, title, description, label, destination) in zip(st.columns(3), actions):
                with column, st.container(border=True):
                    st.markdown(f'<span class="action-icon" aria-hidden="true">{icon}</span>', unsafe_allow_html=True)
                    st.markdown(f"**{title}**")
                    st.caption(description)
                    if st.button(label, key=f"quick_{destination}", use_container_width=True,
                                 type="primary" if destination == "Inspectie" else "secondary"):
                        st.session_state["navigate_to"] = destination
                        st.rerun()
    st.markdown("### Projectoverzicht")
    if not projects:
        st.info("Er zijn nog geen projecten. Maak hierboven het eerste project aan.")
        return
    for item in projects:
        with st.expander(f"{item['name']} · {item['complex_count']} complex(en) · {item['report_count']} rapport(en)"):
            complexes = list_complexes(int(item["id"]))
            if not complexes:
                st.caption("Nog geen complexen.")
            for complex_row in complexes:
                st.markdown(f"**└─ {complex_row['complex_number'] or '—'} · {complex_row['name']}**")
                reports = list_reports(int(complex_row["id"]))
                if not reports:
                    st.caption("　└─ Nog geen rapport")
                for report_row in reports:
                    st.caption(f"　└─ {report_row['title']} · {report_row['status']}")
    if report:
        st.markdown("### Actief rapport")
        r1, r2, r3 = st.columns(3)
        r1.metric("Maatregelen", measures)
        r2.metric("Overige bevindingen", other)
        r3.metric("Gekoppelde foto's", photos)


def render_readonly_report(project, section):
    require('view', project['project_id'])
    st.info('Je hebt voor dit project alleen leesrechten voor dit onderdeel.')
    if section == 'Inspectie':
        render_findings(project)
    elif section == 'Situatie':
        for key in ('voorgevel', 'kopgevel', 'achtergevel', 'luchtfoto'):
            path = absolute_photo(project.get(f'photo_{key}'))
            if path:
                st.image(path, caption=key, use_container_width=True)
    else:
        fields = BUILDING_FIELDS + INSTALLATION_FIELDS + ORGANISATION_FIELDS + MATERIAL_FIELDS if section == 'Algemene gegevens' else [(k, k.replace('_', ' ').capitalize()) for k in ('title', 'kenmerk', 'report_date', 'version', 'status', 'inspecteur', 'gecontroleerd', 'opdrachtgever_contact')]
        st.dataframe([{'Gegeven': label, 'Waarde': str(project.get(key, ''))} for key, label in fields], hide_index=True)
        if section == 'Algemene gegevens':
            for key in ('algemene_omschrijving', 'bezochte_woningen', 'beperkingen'):
                st.markdown(f"**{key.replace('_', ' ').capitalize()}**")
                st.write(project.get(key, ''))


def main() -> None:
    set_actor()
    st.set_page_config(page_title="TriaCon Brandveiligheidsinspectie", page_icon="🔴", layout="wide")
    logo = logo_data_uri()
    st.markdown("<style>" + (APP_DIR / "assets" / "app.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)
    init_db()
    user = authenticated_user()
    if user is None:
        render_auth_page()
        return
    if user['must_change_password']:
        st.warning('Wijzig eerst je tijdelijke wachtwoord. Daarna kun je opnieuw inloggen en de app gebruiken.')
        render_account_controls(user)
        return
    # Preserve the selected inspection when its widgets are temporarily hidden.
    for key in ("selected_project_id", "selected_complex_id", "selected_report_id", "report_navigation"):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    with st.sidebar:
        st.image(str(LOGO_PATH), use_container_width=True)
        st.markdown('<div class="sidebar-label">WERKOMGEVING</div>', unsafe_allow_html=True)
        modules = ["Inspecties", "Kwaliteitscontroles", "Quickscan"] + (['Beheer'] if allowed('manage_users') else [])
        if st.session_state.get('active_module') not in modules:
            st.session_state['active_module'] = 'Inspecties'
        module = st.radio("Modules", modules, key="active_module", width="stretch")
        st.caption("TriaCon · Vastgoedveiligheid")
        st.divider()
        render_account_controls(user)
    st.markdown(
        f'<header class="triacon-header"><div><div class="eyebrow">TriaCon / Vastgoedveiligheid</div><h1>{module}</h1><p>Inspecteren op locatie · rapporteren op kantoor</p></div><div class="header-brand"><img src="{logo}" alt="TriaCon-logo"></div></header>',
        unsafe_allow_html=True,
    )
    if module == 'Beheer':
        render_admin()
        return
    if module != "Inspecties":
        st.markdown(f'<section class="module-placeholder"><span class="module-badge">BINNENKORT</span><h2>{module}</h2><p>Deze module wordt later ingericht. Je projecten en inspectierapporten blijven beschikbaar onder Inspecties.</p></section>', unsafe_allow_html=True)
        return
    context = hierarchy_selector(user)
    render_breadcrumbs(context)
    choices = load_choices()
    show_flash()
    if not context.get("report"):
        render_dashboard(context)
        return
    project = context["report"]
    if st.session_state.get("drawing_report_id") != project["id"]:
        st.session_state.pop("drawing_location", None)
        st.session_state.pop("navigate_to", None)
        st.session_state.pop("report_bytes", None)
        st.session_state.pop("cost_estimate_bytes", None)
        st.session_state["drawing_report_id"] = project["id"]
    if "navigate_to" in st.session_state:
        st.session_state["report_navigation"] = st.session_state.pop("navigate_to")
    labels = ["Dashboard", "Project & complex", "Rapportgegevens", "Algemene gegevens", "Situatie", "Tekeningen", "Inspectie", "Bevindingen", "Rapport"]
    tabs = st.tabs(labels, key="report_navigation", on_change="rerun")
    handlers = [lambda: render_dashboard(context), lambda: render_hierarchy_data(context),
                lambda: render_report_data(project), lambda: render_general_data(project),
                lambda: render_situation(project), lambda: render_drawings(project),
                lambda: render_add_finding(project, choices), lambda: render_findings(project),
                lambda: render_report(project)]
    for label, tab, handler in zip(labels, tabs, handlers):
        if tab.open:
            with tab:
                if label in ('Rapportgegevens', 'Algemene gegevens', 'Situatie', 'Inspectie') and not allowed('edit_report', project['project_id']):
                    render_readonly_report(project, label)
                else:
                    handler()


if __name__ == "__main__":
    try:
        main()
    except PermissionError as exc:
        st.session_state.pop('report_bytes', None)
        st.session_state.pop('cost_estimate_bytes', None)
        st.error(str(exc))
