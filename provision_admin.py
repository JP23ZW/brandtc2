"""Local/server operator command; credentials are never written to source files."""
import getpass
import storage
from user_admin import ROOT_EMAIL, bootstrap_admin


def main():
    storage.init_db()
    with storage.connect() as con:
        exists = con.execute("SELECT value FROM app_settings WHERE key='root_provisioned'").fetchone()
    if exists:
        print('De hoofdbeheerder is al ingericht. Het wachtwoord wordt niet opnieuw ingesteld.')
        return
    print(f'Eenmalige inrichting hoofdbeheerder: Joost Prikken ({ROOT_EMAIL})')
    password = getpass.getpass('Startwachtwoord: ')
    confirm = getpass.getpass('Herhaal startwachtwoord: ')
    if password != confirm:
        raise SystemExit('Wachtwoorden komen niet overeen; niets gewijzigd.')
    bootstrap_admin(password)
    print('Hoofdbeheerder ingericht. Bij de eerste login is een wachtwoordwijziging verplicht.')


if __name__ == '__main__':
    main()
