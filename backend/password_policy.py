"""Shared policy for newly chosen passwords; existing logins remain compatible."""
import unicodedata

MESSAGE='La contraseña debe tener entre 12 y 128 caracteres, una mayúscula, un número y un carácter especial.'


def valid_password(value):
    return (12<=len(value)<=128 and any(unicodedata.category(c)=='Lu' for c in value)
            and any(c in '0123456789' for c in value)
            and any(unicodedata.category(c)[0] in {'P','S'} for c in value)
            and not any(unicodedata.category(c)=='Cc' for c in value))
