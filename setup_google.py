"""One-time guided setup for Google Calendar + Gmail integration.

Walks the user through the Google Cloud Console steps in plain English,
then runs the local OAuth dance (browser popup). After this completes
once, dailybot can read calendar + Gmail and save email drafts forever.

The bot can NEVER send mail — the only Gmail write scope is gmail.compose
(drafts only). The user reviews and sends from Gmail itself.

Run:  make google-setup"""
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from dailybot.oauth import CONFIG_DIR, CREDS_PATH, TOKEN_PATH


console = Console()


STEP_1 = """
**Step 1 / 4 — Create a Google Cloud project**

Open https://console.cloud.google.com in your browser.

1. Top bar → project dropdown → **New Project**
2. Name: `dailybot` (any name works)
3. Click **Create**, then select the new project.
"""

STEP_2 = """
**Step 2 / 4 — Enable the APIs**

Left menu → **APIs & Services → Library**.

Enable each of these (search, click, **Enable**):
- Google Calendar API
- Gmail API
"""

STEP_3 = """
**Step 3 / 4 — OAuth consent screen**

Left menu → **APIs & Services → OAuth consent screen**.

1. User Type: **External** → Create.
2. App name: `dailybot`. Support email: your own.
3. Scopes: skip (we set them programmatically).
4. Test users: **Add your own Google email**. (Required while the app is
   in 'testing' mode.)
5. Save.
"""

STEP_4 = """
**Step 4 / 4 — Create the OAuth client + download credentials**

Left menu → **APIs & Services → Credentials**.

1. **+ Create Credentials → OAuth client ID**.
2. Application type: **Desktop app**. Name: `dailybot`.
3. Click **Create**.
4. The dialog gives you a **Download JSON** button. Click it.
5. The file is named something like `client_secret_xxx.json`. Move/rename
   it to:

   ```
   ~/.config/dailybot/credentials.json
   ```
"""


def banner() -> None:
    console.clear()
    console.print(Panel(
        "[bold green]One-time Google setup for dailybot[/]\n\n"
        "This connects dailybot to your Google Calendar (read-only) and your\n"
        "Gmail account (read + save drafts). The bot can NEVER send mail —\n"
        "the only Gmail write scope is [bold]gmail.compose[/], so drafts only.\n\n"
        "Takes ~10 minutes. After this you never have to do it again.\n\n"
        "Press [bold]Ctrl+C[/] anytime to bail out.",
        title="🔐 dailybot · Google setup", border_style="green",
    ))


def show_step(text: str) -> None:
    console.print(Panel(Markdown(text), border_style="cyan"))
    Prompt.ask("[dim]Done? Press Enter for the next step[/]", default="")


def check_credentials_file() -> bool:
    console.print(Panel(
        f"[bold]Looking for[/] [cyan]{CREDS_PATH}[/] …",
        border_style="yellow",
    ))
    if CREDS_PATH.exists():
        console.print("[bold green]✅ Found credentials.json — nice.[/]")
        return True
    console.print(
        f"[bold red]❌ Not found at {CREDS_PATH}.[/]\n\n"
        "If the file is downloaded but in another place, run:\n"
        f"   [bold]mkdir -p {CONFIG_DIR} && mv ~/Downloads/client_secret_*.json {CREDS_PATH}[/]\n"
    )
    return False


def run_oauth() -> bool:
    console.print(Panel(
        "[bold]Opening your browser for the consent screen …[/]\n\n"
        "You'll see Google's 'this app isn't verified' warning — that's normal\n"
        "for personal apps in 'testing' mode. Click **Advanced → Go to dailybot\n"
        "(unsafe)**. The 'unsafe' is misleading — it just means Google hasn't\n"
        "audited your project. It's your own project.\n\n"
        "Then click **Continue** through the scopes. After it succeeds the\n"
        "browser will show a 'You may close this window' page.",
        title="🌐 OAuth", border_style="cyan",
    ))
    if not Confirm.ask("Ready to open the browser?", default=True):
        console.print("[yellow]Skipped. Re-run `make google-setup` when ready.[/]")
        return False
    try:
        from dailybot.oauth import get_credentials
        get_credentials(interactive=True)
    except Exception as exc:
        console.print(f"[red]OAuth failed:[/] {type(exc).__name__}: {exc}")
        return False
    console.print(f"[bold green]✅ Token saved to {TOKEN_PATH}[/]")
    return True


def smoke_check() -> None:
    console.print("\n[bold]Smoke check:[/] reading today's calendar …")
    try:
        from dailybot.tools.calendar import calendar_today
        result = calendar_today()
        if result["status"] == "ok":
            console.print(
                f"[bold green]✅ Calendar OK[/] — {result['count']} event(s) today."
            )
        else:
            console.print(f"[red]Calendar test failed:[/] {result.get('error')}")
    except Exception as exc:
        console.print(f"[red]Calendar test failed:[/] {exc}")

    console.print("\n[bold]Smoke check:[/] reading inbox top 1 …")
    try:
        from dailybot.tools.gmail import gmail_inbox_recent
        result = gmail_inbox_recent(n=1)
        if result["status"] == "ok":
            console.print(
                f"[bold green]✅ Gmail OK[/] — found {result['count']} message(s)."
            )
        else:
            console.print(f"[red]Gmail test failed:[/] {result.get('error')}")
    except Exception as exc:
        console.print(f"[red]Gmail test failed:[/] {exc}")


def main() -> None:
    banner()
    Prompt.ask("\n[dim]Ready to start? Press Enter[/]", default="")

    show_step(STEP_1)
    show_step(STEP_2)
    show_step(STEP_3)
    show_step(STEP_4)

    while not check_credentials_file():
        if not Confirm.ask(
            "I just moved the file there — check again?", default=True,
        ):
            console.print("[yellow]Bailing — re-run when ready.[/]")
            sys.exit(0)

    if not run_oauth():
        sys.exit(1)
    smoke_check()

    console.print(Panel(
        "[bold green]🎉 Google setup complete![/]\n\n"
        "Now you can:\n"
        "  • ask dailybot [bold]'what's on my calendar today?'[/]\n"
        "  • ask it [bold]'draft a reply to the latest email from <person>'[/]\n"
        "    (it saves to Drafts; you send from Gmail)\n\n"
        "Run [bold cyan]make chat[/] to chat.",
        border_style="green",
    ))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Bye! Re-run `make google-setup` any time.[/]")
