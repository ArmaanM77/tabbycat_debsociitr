import csv
import io
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import formataddr
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from tournaments.forms import TournamentStartForm
from tournaments.models import Tournament
from users.models import Membership

from ...presets import (
    DebSocAsianParliamentaryPreferences,
    DebSocBritishParliamentaryPreferences,
)


DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1HuvRJgz1w3Rs3HFhHgj99W3JhJJEUyDmTKo8tXzHNmc/export?format=csv"
)
PASSWORD_ADJECTIVES = (
    "Bright", "Calm", "Clever", "Golden", "Happy", "Kind", "Lucky", "Quick",
)
PASSWORD_NOUNS = (
    "Falcon", "Mango", "River", "Tiger", "Tulip", "Willow", "Comet", "Panda",
)
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


SPEAKER_GUIDE = """
<h4>Speaker scoring guide</h4>
<p>Use the full range of the scale. “Arguments” includes both constructive
material and responses.</p>
<div class="table-responsive"><table class="table table-sm table-bordered">
<thead><tr><th>Band</th><th>General description</th></tr></thead><tbody>
<tr><td>95–100</td><td>Plausibly one of the best debating speeches ever given;
incredibly difficult to answer; flawless and compelling arguments.</td></tr>
<tr><td>92–94</td><td>An incredible speech and one of the best at the competition;
exceptionally well-made arguments with no flaws of significance.</td></tr>
<tr><td>89–91</td><td>Brilliant engagement with the main issues; sophisticated,
well-explained responses; only very minor problems.</td></tr>
<tr><td>86–88</td><td>Arguments engage with core issues; no logical gaps; only
minor flaws.</td></tr>
<tr><td>83–85</td><td>Arguments address the core issues and are strong, though
occasional failures to respond or limited flaws remain.</td></tr>
<tr><td>79–82</td><td>Relevant arguments addressing the core issues, well-made
without obvious logical gaps, though vulnerable to good responses.</td></tr>
<tr><td>76–78</td><td>Mostly relevant arguments addressing most core issues;
occasional simplistic, peripheral, or irrelevant material.</td></tr>
<tr><td>73–75</td><td>Almost exclusively relevant but may not address enough core
issues; logical yet simplistic and vulnerable to competent responses.</td></tr>
<tr><td>70–72</td><td>Frequently relevant arguments with some explanation, but
regular significant logical gaps.</td></tr>
<tr><td>67–69</td><td>Generally relevant and mostly explained, but with significant
logical gaps; generally clear.</td></tr>
<tr><td>64–66</td><td>Sometimes relevant but often unclear; significant logical gaps
make it difficult to credit the material.</td></tr>
<tr><td>61–63</td><td>Some relevant claims and occasional explanations, but
significant gaps; frequently unclear and confusing.</td></tr>
<tr><td>58–60</td><td>Claims are occasionally relevant but are not formulated as
arguments; hard to follow.</td></tr>
<tr><td>55–57</td><td>One or two marginally relevant claims; mostly comments rather
than arguments; hard to follow.</td></tr>
<tr><td>50–55</td><td>Content is not relevant, does not go beyond claims, and is
confusing; very hard to follow.</td></tr>
</tbody></table></div>
"""


ADJUDICATOR_GUIDE = """
<h4>Adjudicator scoring guide</h4>
<p>Scores assess the accuracy of the call and the quality of its
reasoning/justification.</p>
<div class="table-responsive"><table class="table table-sm table-bordered">
<thead><tr><th>Score</th><th>Guide</th></tr></thead><tbody>
<tr><td>10 — Exceptional</td><td>Extremely accurate call with meticulous
assessment of close comparisons. Flawless or near-flawless, in-depth,
insightful and nuanced justification, with explicit identification and strong
justification of any weighing metrics or assumptions used.</td></tr>
<tr><td>9 — Excellent</td><td>Very accurate call and correct assessment of close
comparisons, with comprehensive recognition of necessary inter-team
comparisons. Very well-outlined, in-depth, insightful and nuanced
justification, with good attempts to justify weighing metrics.</td></tr>
<tr><td>8 — Very Good</td><td>Accurate call with detailed recognition of most
necessary comparisons. Comprehensive, in-depth and nuanced justification, with
only very occasional minor assumptions, personal bias, or lack of clarity;
judging metrics are identified but not explicitly justified.</td></tr>
<tr><td>7 — Good</td><td>Generally correct ranking with possible errors on close
comparisons and careful acknowledgement of most necessary comparisons.
Generally well-outlined justification, with occasional minor bias, assumptions,
or lack of clarity.</td></tr>
<tr><td>6 — Above Average</td><td>Mostly accurate call that may miss close
comparisons. Good attempt at justification showing some appreciation of key
clashes and how they are resolved, with occasional minor assumptions or lack
of clarity.</td></tr>
<tr><td>5 — Average</td><td>Broadly accurate on obvious clashes but may mishandle
close comparisons or neglect a significant but non-substantial part of the
debate. Some attempt at justification, but regular slippage into personal bias
and assumptions and lack of clarity on specific comparisons.</td></tr>
<tr><td>4 — Below Average</td><td>Inaccurate call despite identifying clashes;
one or more misunderstandings of the debate, with difficulty tracking important
arguments or responses. Unsatisfactory justification, frequent bias and
assumptions, and lack of clarity on most comparisons.</td></tr>
<tr><td>3 — Poor</td><td>Inaccurate call with fundamental misunderstandings;
failure to identify the call correctly, and difficulty tracking important
arguments or responses. Poor justification showing no appreciation of key
clashes, with severe bias, distortion, and lack of clarity.</td></tr>
<tr><td>2 — Very Poor</td><td>Wildly inaccurate rankings and core
misunderstandings, with clear inability to track important arguments or
responses. Little or no justification, frequent bias and irrelevance, and lack
of clarity on most inter-team comparisons.</td></tr>
<tr><td>1 — Abysmal</td><td>Completely inaccurate call with foundational
misunderstanding of both the debate and debating generally, with clear inability
to track important arguments or responses. No rationalisable justification,
deeply erroneous appreciation of key clashes, and utter irrelevance.</td></tr>
</tbody></table></div>
"""


@dataclass(frozen=True)
class Member:
    name: str
    email: str
    username: str
    password: str


class Command(BaseCommand):
    help = (
        "Create the monthly DebSoc APD/BPD tournaments and rotate credentials "
        "for every member in the configured public Google Sheet."
    )

    def add_arguments(self, parser):
        parser.add_argument("--sheet-url", default=os.environ.get("DEBSOC_MEMBERS_CSV_URL", DEFAULT_SHEET_URL))
        parser.add_argument("--skip-email", action="store_true")
        parser.add_argument("--email-delay", type=float, default=float(os.environ.get("DEBSOC_EMAIL_DELAY", "1")))

    def handle(self, *args, **options):
        now = timezone.localtime()
        members = self._load_members(options["sheet_url"])
        tournaments = self._ensure_tournaments(now)
        self._validate_account_conflicts(members)

        if not options["skip_email"]:
            self._validate_email_settings()
            self._send_credentials(members, tournaments, options["email_delay"])

        self._save_users_and_memberships(members, tournaments)
        self.stdout.write(self.style.SUCCESS(
            f"Bootstrapped {len(tournaments)} tournaments and rotated {len(members)} member credentials."
        ))

    def _load_members(self, url):
        try:
            request = Request(url, headers={"User-Agent": "Tabbycat-DebSoc-Bootstrap/1.0"})
            with urlopen(request, timeout=30) as response:
                content = response.read().decode("utf-8-sig")
        except Exception as exc:
            raise CommandError(f"Could not download member CSV: {exc}") from exc

        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames or not {"Name", "Email"}.issubset(reader.fieldnames):
            raise CommandError("Member CSV must contain Name and Email columns.")

        members = []
        usernames = set()
        emails = set()
        for row_number, row in enumerate(reader, start=2):
            name = (row.get("Name") or "").strip()
            email = (row.get("Email") or "").strip().lower()
            if not name and not email:
                continue
            if not name or not email:
                raise CommandError(f"Row {row_number} must contain both Name and Email.")
            try:
                validate_email(email)
            except ValidationError as exc:
                raise CommandError(f"Row {row_number} has an invalid email address: {email!r}.") from exc
            username = self._username_for(name)
            if username.casefold() in usernames:
                raise CommandError(f"Duplicate generated username {username!r} at row {row_number}.")
            if email in emails:
                raise CommandError(f"Duplicate email {email!r} at row {row_number}.")
            usernames.add(username.casefold())
            emails.add(email)
            members.append(Member(name, email, username, self._new_password()))

        if not members:
            raise CommandError("Member CSV contains no members.")
        return members

    @staticmethod
    def _username_for(name):
        compact = re.sub(r"[^A-Za-z0-9]", "", name)
        if not compact:
            raise CommandError(f"Cannot generate a username from {name!r}.")
        return f"T-{compact}"[:150]

    @staticmethod
    def _new_password():
        adjective = secrets.choice(PASSWORD_ADJECTIVES)
        noun = secrets.choice(PASSWORD_NOUNS)
        suffix = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(8))
        return f"{adjective}-{noun}-{suffix}"

    @staticmethod
    def _validate_account_conflicts(members):
        User = get_user_model()
        for member in members:
            email_matches = User.objects.filter(email__iexact=member.email)
            if email_matches.count() > 1:
                raise CommandError(f"Multiple users already use {member.email}.")
            email_user = email_matches.first()
            username_user = User.objects.filter(username__iexact=member.username).first()
            if username_user is not None and username_user != email_user:
                raise CommandError(
                    f"Username {member.username} belongs to another email address."
                )

    def _ensure_tournaments(self, now: datetime):
        month = now.strftime("%B")
        year = now.strftime("%y")
        specs = (
            ("apd", DebSocAsianParliamentaryPreferences),
            ("bpd", DebSocBritishParliamentaryPreferences),
        )
        tournaments = []
        for prefix, preset in specs:
            display_name = f"{prefix}-{month}-{year}"
            slug = display_name.lower()
            tournament = Tournament.objects.filter(slug=slug).first()
            if tournament is None:
                form = TournamentStartForm(data={
                    "name": display_name,
                    "short_name": display_name,
                    "slug": slug,
                    "num_prelim_rounds": 10,
                    "break_size": "",
                })
                if not form.is_valid():
                    raise CommandError(f"Could not create {display_name}: {form.errors.as_json()}")
                tournament = form.save()
                self.stdout.write(f"Created tournament {display_name}.")
            else:
                self.stdout.write(f"Tournament {display_name} already exists; refreshing its DebSoc preset.")

            preset.save(tournament)
            tournament.preferences["scoring__ballot_introduction"] = SPEAKER_GUIDE
            tournament.preferences["feedback__feedback_introduction"] = ADJUDICATOR_GUIDE
            tournaments.append(tournament)
        return tournaments

    def _validate_email_settings(self):
        required = ("EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL")
        missing = [name for name in required if not getattr(settings, name, None)]
        if missing:
            raise CommandError("Email is not configured; missing " + ", ".join(missing))

    def _send_credentials(self, members, tournaments, delay):
        connection = mail.get_connection(fail_silently=False)
        connection.open()
        try:
            for index, member in enumerate(members):
                tournament_names = ", ".join(t.name for t in tournaments)
                hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
                login_line = f"Login: https://{hostname}/accounts/login/\n" if hostname else ""
                subject = "Your new DebSoc Tabbycat credentials"
                body = (
                    f"Hi {member.name},\n\n"
                    "A new DebSoc Tabbycat deployment has been prepared. "
                    "Your previous password has been replaced.\n\n"
                    f"Username: {member.username}\n"
                    f"Password: {member.password}\n"
                    f"{login_line}"
                    f"Tournaments: {tournament_names}\n\n"
                    "Please keep these credentials private.\n"
                )
                message = mail.EmailMessage(
                    subject=subject,
                    body=body,
                    from_email=formataddr(("DebSoc Tabulation", settings.DEFAULT_FROM_EMAIL)),
                    to=[formataddr((member.name, member.email))],
                    connection=connection,
                    headers={"Auto-Submitted": "auto-generated"},
                )
                sent = message.send()
                if sent != 1:
                    raise CommandError(f"SMTP did not accept the credential email for {member.email}.")
                if delay > 0 and index < len(members) - 1:
                    time.sleep(delay)
        except Exception as exc:
            raise CommandError(
                "Credential email delivery failed. No passwords were rotated; "
                f"fix SMTP and redeploy. Error: {exc}"
            ) from exc
        finally:
            connection.close()

    @transaction.atomic
    def _save_users_and_memberships(self, members, tournaments):
        User = get_user_model()
        for index, member in enumerate(members):
            user = User.objects.filter(email__iexact=member.email).first()
            if user is None:
                user = User(email=member.email)

            user.username = member.username
            user.email = member.email
            user.first_name = member.name
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            user.set_password(member.password)
            user.save()

            if index == 0:
                for tournament in tournaments:
                    tab_director = tournament.group_set.get(name="Tabulation Director")
                    Membership.objects.get_or_create(user=user, group=tab_director)

            role = "global superuser + Tabulation Director" if index == 0 else "global superuser"
            self.stdout.write(f"Rotated {member.username} ({role}).")
