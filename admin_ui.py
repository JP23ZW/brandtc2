"""Administrator screens; all mutations also authorize in user_admin."""
import json
import streamlit as st
import storage
import user_admin
from access_control import ROLES, PROJECT_ROLES, PERMISSIONS, allowed, require


def render_admin():
    require('manage_users')
    st.subheader('Gebruikers en projectrechten')
    st.caption('Beheerders hebben toegang tot alle projecten. Andere gebruikers zien alleen projecten waaraan zij zijn gekoppeld. Een expliciet projectrecht gaat vóór de standaard projectrol.')
    users = user_admin.list_users()
    with st.expander('Account aanmaken'):
        with st.form('admin_new_user'):
            name = st.text_input('Naam')
            email = st.text_input('E-mailadres')
            password = st.text_input('Tijdelijk wachtwoord (minimaal 12 tekens)', type='password')
            if st.form_submit_button('Account aanmaken'):
                try:
                    if len(password) < 12:
                        raise ValueError('Gebruik minimaal 12 tekens.')
                    uid = storage.register_user(name, email, password)
                    user_admin.reset_password(uid, password)
                    st.success('Account aangemaakt. Activeer het hieronder en koppel projecten.')
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
    if users:
        by_id = {u['id']: u for u in users}
        uid = st.selectbox('Gebruiker beheren', list(by_id), format_func=lambda i: f"{by_id[i]['name']} · {by_id[i]['email']}" + (' · wacht op goedkeuring/geblokkeerd' if not by_id[i]['is_active'] else ''))
        user = by_id[uid]
        if user['role'] == 'superadmin':
            st.info('Joost Prikken is de beschermde hoofdbeheerder met alle rechten. Het wachtwoord kan uitsluitend via het eigen account worden gewijzigd.')
        elif user['role'] == 'admin' and not allowed('manage_admins'):
            st.info('Alleen de hoofdbeheerder kan beheerdersaccounts aanpassen.')
        else:
            roles = ['projectleider', 'adviseur', 'lezer'] + (['admin'] if allowed('manage_admins') else [])
            with st.form(f'admin_user_{uid}'):
                role = st.selectbox('Accountrol', roles, index=roles.index(user['role']), format_func=ROLES.get)
                active = st.checkbox('Account actief / registratie goedgekeurd', value=bool(user['is_active']))
                create = st.checkbox('Mag nieuwe projecten aanmaken', value=bool(user['can_create_project']))
                st.caption('Een eigen nieuw project krijgt de accountrol als projectrol. Complexen aanmaken kan daarna per project apart worden toegekend. Beheerders hebben dit recht altijd.')
                if st.form_submit_button('Accountrechten opslaan'):
                    try:
                        user_admin.update_user(uid, role, active, create)
                    except (ValueError, PermissionError) as exc:
                        st.error(str(exc))
                    else:
                        st.success('Opgeslagen. Bestaande sessies van deze gebruiker zijn ongeldig gemaakt.')
                        st.rerun()
            with st.expander('Wachtwoord opnieuw instellen'):
                with st.form(f'admin_reset_{uid}'):
                    temporary = st.text_input('Nieuw tijdelijk wachtwoord', type='password')
                    confirm = st.text_input('Bevestig tijdelijk wachtwoord', type='password')
                    if st.form_submit_button('Wachtwoord resetten'):
                        try:
                            if temporary != confirm:
                                raise ValueError('Wachtwoorden komen niet overeen.')
                            user_admin.reset_password(uid, temporary)
                        except (ValueError, PermissionError) as exc:
                            st.error(str(exc))
                        else:
                            st.success('Wachtwoord gereset. Bij inloggen moet de gebruiker een eigen wachtwoord kiezen.')
    st.divider()
    st.markdown('### Projecttoegang')
    projects = storage.list_projects()
    candidates = {u['id']: u for u in users if u['role'] not in ('superadmin', 'admin')}
    if projects and candidates:
        projects_by_id = {p['id']: p for p in projects}
        pid = st.selectbox('Project', list(projects_by_id), format_func=lambda i: projects_by_id[i]['name'])
        uid = st.selectbox('Adviseur / gebruiker koppelen', list(candidates), format_func=lambda i: f"{candidates[i]['name']} · {candidates[i]['email']}")
        memberships = {m['user_id']: m for m in user_admin.memberships(pid)}
        member = memberships.get(uid)
        role = st.selectbox('Projectrol', list(PROJECT_ROLES), index=list(PROJECT_ROLES).index(member['role'] if member else (candidates[uid]['role'] if candidates[uid]['role'] in PROJECT_ROLES else 'adviseur')), format_func=ROLES.get, key=f'membership_role_{pid}_{uid}')
        overrides = json.loads(member['permissions_json']) if member and member['role'] == role else {}
        with st.form(f'project_rights_{pid}_{uid}_{role}'):
            rights = {p: st.checkbox(label, value=overrides.get(p, p in PROJECT_ROLES[role]), key=f'right_{pid}_{uid}_{role}_{p}') for p, label in PERMISSIONS.items()}
            if st.form_submit_button('Projectkoppeling en rechten opslaan', type='primary'):
                user_admin.assign_project(pid, uid, role, rights)
                st.success('Projectrechten opgeslagen.')
                st.rerun()
        if member and st.button('Gebruiker van dit project loskoppelen', key=f'remove_{pid}_{uid}'):
            user_admin.remove_project_member(pid, uid)
            st.rerun()
        st.dataframe([{'Gebruiker': candidates[m['user_id']]['name'], 'Projectrol': ROLES[m['role']]} for m in memberships.values() if m['user_id'] in candidates], hide_index=True)
    else:
        st.info('Maak eerst een project en een niet-beheerdersaccount aan.')
    with st.expander('Laatste beheerwijzigingen'):
        st.dataframe(user_admin.recent_audit(), hide_index=True)
