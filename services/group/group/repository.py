from contextlib import closing

import pymssql

import database


def add_member(name: str) -> int:
    """save a new active member and return their id"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute("INSERT INTO members (name) OUTPUT INSERTED.id VALUES (%s)", (name,))
        member_id = cursor.fetchone()["id"]
        connection.commit()
        return member_id


def get_member(member_id: int) -> dict | None:
    """return one member, or None if no member has that id"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT id, name, is_active FROM members WHERE id = %s", (member_id,))
        member = cursor.fetchone()
    return member


def list_members() -> list[dict]:
    """return every member, active and archived, sorted by name"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT id, name, is_active FROM members ORDER BY name")
        members = cursor.fetchall()
    return members


def archive_member(member_id: int) -> bool:
    """mark a member inactive and return False if no member has that id"""
    return _set_member_active(member_id, 0)


def reactivate_member(member_id: int) -> bool:
    """mark an archived member active again and return False if no member has that id"""
    return _set_member_active(member_id, 1)


def create_night(
    night_date: str, available_minutes: int, attendee_ids: list[int], guest_names: list[str]
) -> int:
    """save a night with its attendees and guests in one transaction and return its id"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO nights (night_date, available_minutes) OUTPUT INSERTED.id VALUES (%s, %s)",
                (night_date, available_minutes),
            )
            night_id = cursor.fetchone()["id"]

            for member_id in attendee_ids:
                cursor.execute(
                    "INSERT INTO night_attendees (night_id, member_id) VALUES (%s, %s)",
                    (night_id, member_id),
                )
            for guest_name in guest_names:
                cursor.execute(
                    "INSERT INTO night_guests (night_id, guest_name) VALUES (%s, %s)",
                    (night_id, guest_name),
                )
            # one commit at the end, so the night is saved together with all its attendees and guests or not at all
            connection.commit()
        except pymssql.Error:
            connection.rollback()
            raise
        return night_id


def get_night(night_id: int) -> dict | None:
    """return a night with its attendees and guests, or None if it does not exist"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        # style 23 turns the DATE back into YYYY-MM-DD text, the format the service code and the API already use
        cursor.execute(
            "SELECT id, CONVERT(NVARCHAR(10), night_date, 23) AS night_date, available_minutes"
            " FROM nights WHERE id = %s",
            (night_id,),
        )
        night = cursor.fetchone()
        if night is None:
            return None

        cursor.execute(
            "SELECT members.id, members.name FROM night_attendees"
            " JOIN members ON members.id = night_attendees.member_id"
            " WHERE night_attendees.night_id = %s ORDER BY members.name",
            (night_id,),
        )
        night["attendees"] = cursor.fetchall()

        cursor.execute(
            "SELECT guest_name FROM night_guests WHERE night_id = %s ORDER BY guest_name",
            (night_id,),
        )
        guest_rows = cursor.fetchall()

    night["guests"] = []
    for guest_row in guest_rows:
        night["guests"].append(guest_row["guest_name"])
    return night


def save_rating(member_id: int, game_id: int, score: int) -> None:
    """save a member's score for a game, replacing their old score if they had one"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        # SQL Server has no ON CONFLICT, so the existing score is updated first and a new row is inserted only if there was none
        cursor.execute(
            "UPDATE ratings SET score = %s WHERE member_id = %s AND game_id = %s;"
            " IF @@ROWCOUNT = 0"
            " INSERT INTO ratings (member_id, game_id, score) VALUES (%s, %s, %s)",
            (score, member_id, game_id, member_id, game_id, score),
        )
        connection.commit()


def get_ratings_by_member(member_id: int) -> dict[int, int]:
    """return a member's scores as a dict of game id to score"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT game_id, score FROM ratings WHERE member_id = %s", (member_id,))
        rows = cursor.fetchall()
    scores = {}
    for row in rows:
        scores[row["game_id"]] = row["score"]
    return scores


def log_play(night_id: int, game_id: int) -> int:
    """record that a game was played on a night and return the play's id"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO plays (night_id, game_id) OUTPUT INSERTED.id VALUES (%s, %s)",
            (night_id, game_id),
        )
        play_id = cursor.fetchone()["id"]
        connection.commit()
        return play_id


def get_last_played_dates() -> dict[int, str]:
    """return a dict of game id to the date of the most recent night it was played"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT plays.game_id, CONVERT(NVARCHAR(10), MAX(nights.night_date), 23) AS last_played FROM plays"
            " JOIN nights ON nights.id = plays.night_id GROUP BY plays.game_id"
        )
        rows = cursor.fetchall()
    last_played_dates = {}
    for row in rows:
        last_played_dates[row["game_id"]] = row["last_played"]
    return last_played_dates


def get_unrated_plays() -> list[dict]:
    """return each active member and game they played at a night but never rated"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT DISTINCT members.id AS member_id, members.name AS member_name, plays.game_id"
            " FROM members"
            " JOIN night_attendees ON night_attendees.member_id = members.id"
            " JOIN plays ON plays.night_id = night_attendees.night_id"
            " LEFT JOIN ratings ON ratings.member_id = members.id"
            " AND ratings.game_id = plays.game_id"
            " WHERE members.is_active = 1 AND ratings.member_id IS NULL"
            " ORDER BY member_name, game_id"
        )
        unrated_plays = cursor.fetchall()
    return unrated_plays


def _set_member_active(member_id: int, is_active: int) -> bool:
    """set a member's is_active flag and return False if no member has that id"""
    with closing(database.get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute("UPDATE members SET is_active = %s WHERE id = %s", (is_active, member_id))
        updated_count = cursor.rowcount
        connection.commit()
        return updated_count > 0