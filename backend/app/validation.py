"""Field validation. Collect every problem, then raise one 422 listing them all."""

import re

from .routing import HTTPError

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")


class Validator:
    def __init__(self, data):
        if not isinstance(data, dict):
            raise HTTPError(400, "Request body must be a JSON object.")
        self.data = data
        self.errors = {}
        self.clean = {}

    # -- helpers ---------------------------------------------------------
    def _fail(self, field, message):
        self.errors.setdefault(field, message)
        return None

    def has(self, field):
        return field in self.data

    def done(self):
        if self.errors:
            raise HTTPError(422, "Some fields need fixing.", fields=self.errors)
        return self.clean

    # -- field types -----------------------------------------------------
    def text(self, field, required=False, max_length=2000, default=""):
        if field not in self.data:
            if required:
                return self._fail(field, "This field is required.")
            return None
        value = self.data[field]
        if value is None:
            value = ""
        if not isinstance(value, str):
            return self._fail(field, "Expected text.")
        value = value.strip()
        if required and not value:
            return self._fail(field, "This field is required.")
        if len(value) > max_length:
            return self._fail(field, f"Keep this under {max_length} characters.")
        self.clean[field] = value or default
        return self.clean[field]

    def slug(self, field, required=False):
        value = self.text(field, required=required, max_length=80)
        if value is None or field in self.errors:
            return None
        if value and not SLUG_RE.match(value):
            return self._fail(field, "Use lowercase letters, numbers and hyphens only.")
        return value

    def email(self, field, required=False):
        value = self.text(field, required=required, max_length=254)
        if value is None or field in self.errors:
            return None
        if value and not EMAIL_RE.match(value):
            return self._fail(field, "That does not look like an email address.")
        return value

    def phone(self, field, required=True):
        """Accepts what people actually type. Stores the original and the digits."""
        value = self.text(field, required=required, max_length=40)
        if value is None or field in self.errors:
            return None
        digits = re.sub(r"\D", "", value)
        if digits.startswith("1") and len(digits) == 11:
            digits = digits[1:]
        if len(digits) < 10 or len(digits) > 15:
            return self._fail(field, "Enter a phone number with area code, like (336) 555-0184.")
        self.clean[field + "_digits"] = digits
        return value

    def integer(self, field, required=False, minimum=None, maximum=None, default=None):
        if field not in self.data:
            if required:
                return self._fail(field, "This field is required.")
            if default is not None:
                self.clean[field] = default
            return None
        value = self.data[field]
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return self._fail(field, "Expected a whole number.")
        try:
            value = int(value)
        except ValueError:
            return self._fail(field, "Expected a whole number.")
        if minimum is not None and value < minimum:
            return self._fail(field, f"Must be {minimum} or more.")
        if maximum is not None and value > maximum:
            return self._fail(field, f"Must be {maximum} or less.")
        self.clean[field] = value
        return value

    def boolean(self, field, default=None):
        if field not in self.data:
            if default is not None:
                self.clean[field] = default
            return None
        value = self.data[field]
        if isinstance(value, bool):
            self.clean[field] = value
        elif value in (0, 1, "0", "1", "true", "false", "True", "False"):
            self.clean[field] = value in (1, "1", "true", "True")
        else:
            return self._fail(field, "Expected true or false.")
        return self.clean[field]

    def choice(self, field, options, required=False, default=None):
        value = self.text(field, required=required, max_length=40)
        if value is None or field in self.errors:
            if default is not None and field not in self.data:
                self.clean[field] = default
            return None
        if value not in options:
            return self._fail(field, "Must be one of: " + ", ".join(options) + ".")
        return value

    def string_list(self, field, max_items=12, max_length=60, default=None):
        if field not in self.data:
            if default is not None:
                self.clean[field] = default
            return None
        value = self.data[field]
        if not isinstance(value, list):
            return self._fail(field, "Expected a list of short labels.")
        if len(value) > max_items:
            return self._fail(field, f"No more than {max_items} items.")
        cleaned = []
        for item in value:
            if not isinstance(item, str):
                return self._fail(field, "Every item must be text.")
            item = item.strip()
            if not item:
                continue
            if len(item) > max_length:
                return self._fail(field, f"Each item must be under {max_length} characters.")
            cleaned.append(item)
        self.clean[field] = cleaned
        return cleaned


def path_int(request, name):
    """Read an integer id out of the URL, or 404 if it is not a number."""
    raw = request.params.get(name, "")
    if not raw.isdigit():
        raise HTTPError(404, "Not found.")
    return int(raw)
