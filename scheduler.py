import os
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from apscheduler.schedulers.background import BackgroundScheduler
from database import get_connection

scheduler = BackgroundScheduler()
scheduler.start()

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "your-email@gmail.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "your-app-password")
APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")


def check_and_send_rating_reminder(plate_id: int, user_email: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT dish_name, restaurant, rating FROM plates WHERE id = %s",
        (plate_id,),
    )
    plate = c.fetchone()
    c.close()
    conn.close()

    if not plate or plate["rating"] is not None:
        return

    dish_name = plate["dish_name"]
    restaurant = plate["restaurant"]

    msg = EmailMessage()
    msg["Subject"] = f"Finished eating? Rate your {dish_name}!"
    msg["From"] = f"PlateRate <{SMTP_USER}>"
    msg["To"] = user_email

    rate_link = f"{APP_URL}/plates/{plate_id}/rate"
    msg.set_content(
        f"Hey!\n\n"
        f"It's been 45 minutes since you ordered {dish_name} at {restaurant}.\n"
        f"Was it worth it? Give it a rating while the taste is fresh:\n\n"
        f"{rate_link}\n\n"
        f"- The PlateRate Team"
    )

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
            print(f"[Scheduler] Sent reminder email for plate #{plate_id} to {user_email}")
    except Exception as e:
        print(f"[Scheduler] Email sending failed: {e}")


def schedule_rating_reminder(plate_id: int, user_email: str):
    run_time = datetime.now() + timedelta(minutes=45)
    scheduler.add_job(
        check_and_send_rating_reminder,
        "date",
        run_date=run_time,
        args=[plate_id, user_email],
    )
    print(f"[Scheduler] Reminder scheduled for plate #{plate_id} at {run_time}")