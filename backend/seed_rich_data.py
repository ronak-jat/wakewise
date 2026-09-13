import sys
import os
import random
from datetime import datetime, timedelta, timezone, date

# Add current dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import User, Alarm, ChallengeAttempt, AlarmSnoozeEvent
from security import hash_password


def mix_up_database_data():
    db = SessionLocal()
    print("Starting comprehensive database diversification and realistic data mix-up...")

    now = datetime.now()
    default_hashed_pwd = hash_password("password123")

    # Chronotypes & diverse profiles
    chronotypes = [
        {"bed": "21:30", "wake": "05:30", "thresh": 15, "streak_bonus": 14, "accuracy": 0.95, "title": "Early Riser / Athlete"},
        {"bed": "22:15", "wake": "06:15", "thresh": 20, "streak_bonus": 10, "accuracy": 0.92, "title": "Executive Focus"},
        {"bed": "22:45", "wake": "06:45", "thresh": 25, "streak_bonus": 7,  "accuracy": 0.88, "title": "Disciplined Professional"},
        {"bed": "23:00", "wake": "07:00", "thresh": 30, "streak_bonus": 5,  "accuracy": 0.85, "title": "Standard Balanced"},
        {"bed": "23:30", "wake": "07:30", "thresh": 35, "streak_bonus": 4,  "accuracy": 0.82, "title": "Flexible Routine"},
        {"bed": "00:15", "wake": "08:15", "thresh": 40, "streak_bonus": 3,  "accuracy": 0.78, "title": "Late Night Thinker"},
        {"bed": "01:00", "wake": "08:45", "thresh": 45, "streak_bonus": 2,  "accuracy": 0.74, "title": "Night Owl Developer"},
        {"bed": "01:45", "wake": "09:30", "thresh": 50, "streak_bonus": 1,  "accuracy": 0.68, "title": "Creative Freelancer"},
        {"bed": "23:15", "wake": "07:15", "thresh": 30, "streak_bonus": 8,  "accuracy": 0.89, "title": "Consistent Learner"},
        {"bed": "22:00", "wake": "06:00", "thresh": 20, "streak_bonus": 12, "accuracy": 0.94, "title": "Morning Meditation Enthusiast"},
    ]

    alarm_title_bank = [
        "Sunrise Mobility & Yoga", "Deep Work Cognitive Sprint", "Morning Gym & Lift Routine",
        "Hydration & Mind Drill", "Rapid Logic Jumpstart", "Cardio Awakening & Focus",
        "Weekend Leisure Rise", "Academic Study Prep", "High Performance Routine",
        "Daily Breathwork & Rise", "Morning Code Kickoff", "Vitality & Strength Alarm",
        "Midday Refresh Alarm", "Early Bird Momentum", "Circadian Sync Awakening"
    ]

    challenge_types = [
        "Math Problems", "Logic Puzzles", "Memory Challenges", 
        "Word Games", "Pattern Recognition", "Riddles", "Quick Quizzes"
    ]
    difficulties = ["Beginner", "Easy", "Medium", "Hard", "Expert"]
    verification_methods = ["multi_step", "consecutive_correct", "time_based", "accuracy_check", "puzzle_completion"]

    sample_questions = {
        "Math Problems": [
            ("Calculate: 14 * 6 + 18", "102"),
            ("Solve: 85 - 37 + 14", "62"),
            ("What is 12^2 - 44?", "100"),
            ("Calculate: 250 / 5 + 35", "85"),
            ("Solve: 17 * 4 - 23", "45"),
            ("Compute: (48 / 6) * 9", "72"),
            ("What is 15 * 15 - 25?", "200"),
            ("Solve: 13 * 7 + 11", "102"),
        ],
        "Logic Puzzles": [
            ("If all bloops are razzies and all razzies are lazzies, are all bloops definitely lazzies?", "Yes"),
            ("A bat and a ball cost $1.10. The bat costs $1.00 more than the ball. How much does the ball cost?", "$0.05"),
            ("Which direction is opposite of North-West?", "South-East"),
            ("A plane crashes on the border of US and Canada. Where do they bury survivors?", "Nowhere"),
            ("If three cats can catch three mice in three minutes, how many cats are needed to catch 100 mice in 100 minutes?", "3"),
        ],
        "Memory Challenges": [
            ("Recall the sequence: Blue, Red, Green, Yellow, Blue", "Blue, Red, Green, Yellow, Blue"),
            ("What was the 3rd number in 7, 3, 9, 4, 1?", "9"),
            ("Recall the 4-digit code: 8291", "8291"),
            ("Repeat the word trio: Silver, Horizon, Anchor", "Silver, Horizon, Anchor"),
        ],
        "Word Games": [
            ("Unscramble the word: 'IKAWNG'", "WAKING"),
            ("Find an anagram of 'SILENT'", "LISTEN"),
            ("What 5-letter word becomes shorter when you add two letters to it?", "Short"),
            ("Rearrange 'EARTH' into another word for heart rhythm:", "HEART"),
        ],
        "Pattern Recognition": [
            ("What comes next in: 2, 4, 8, 16, ___?", "32"),
            ("Complete the series: 3, 6, 11, 18, ___?", "27"),
            ("What is next: 1, 1, 2, 3, 5, 8, ___?", "13"),
            ("Next letter in: A, C, F, J, ___?", "O"),
        ],
        "Riddles": [
            ("What has hands but cannot clap?", "Clock"),
            ("I speak without a mouth and hear without ears. What am I?", "Echo"),
            ("The more of this there is, the less you see. What is it?", "Darkness"),
            ("What goes up but never comes down?", "Age"),
        ],
        "Quick Quizzes": [
            ("What is the primary neurochemical responsible for circadian sleep cycles?", "Melatonin"),
            ("Which brain wave state is associated with active alertness?", "Beta"),
            ("What gland in the brain controls the circadian body clock?", "Pineal"),
            ("What temperature change naturally signals sleep onset to the body?", "Core cooling"),
        ]
    }

    # 1. Update all users with distinct mixed-up profiles
    users = db.query(User).all()
    print(f"Found {len(users)} users in database to diversify.")

    for idx, u in enumerate(users):
        c_profile = chronotypes[idx % len(chronotypes)]
        u.target_bedtime = c_profile["bed"]
        u.target_wake_time = c_profile["wake"]
        u.inactivity_threshold_minutes = c_profile["thresh"]
        
        # Jitter estimated sleep onset & wake time realistically
        bed_h, bed_m = map(int, c_profile["bed"].split(":"))
        wake_h, wake_m = map(int, c_profile["wake"].split(":"))
        
        jitter_bed = random.randint(-18, 25)
        jitter_wake = random.randint(-12, 22)
        
        yesterday = now - timedelta(days=1)
        est_sleep = yesterday.replace(hour=bed_h, minute=bed_m, second=0) + timedelta(minutes=jitter_bed)
        est_wake = now.replace(hour=wake_h, minute=wake_m, second=0) + timedelta(minutes=jitter_wake)
        
        u.estimated_sleep_start = est_sleep
        u.estimated_sleep_end = est_wake
        u.last_meaningful_activity_at = est_sleep - timedelta(minutes=random.randint(5, 35))
        
        db.add(u)
    db.commit()
    print("Diversified all user profiles with mixed chronotypes, bedtimes, and wake targets.")

    # 2. Diversify Alarms across users
    for idx, u in enumerate(users):
        u_alarms = db.query(Alarm).filter(Alarm.user_id == u.id).all()
        target_w = u.target_wake_time or "07:00"
        tw_h, tw_m = map(int, target_w.split(":"))

        # Create or update 2-4 alarms per user with varied configurations
        desired_alarm_count = random.randint(2, 4)
        while len(u_alarms) < desired_alarm_count:
            alarm = Alarm(
                user_id=u.id,
                title=f"{random.choice(alarm_title_bank)}",
                alarm_time=target_w,
                alarm_type=random.choice(["Daily", "Weekday", "Weekend", "Custom"]),
                repeat_days="Mon,Tue,Wed,Thu,Fri",
                is_active=True,
                challenge=random.choice(challenge_types),
                difficulty_level=random.choice(difficulties),
                verification_method=random.choice(verification_methods),
                time_limit=random.choice([15, 20, 25, 30]),
                snooze_duration=random.choice([5, 8, 10]),
                max_snoozes=random.choice([1, 2, 3, 4]),
            )
            db.add(alarm)
            db.commit()
            db.refresh(alarm)
            u_alarms.append(alarm)

        # Mix up each alarm's details
        for a_idx, alarm in enumerate(u_alarms):
            # Alarm 1: Primary wake alarm near target wake time (Active)
            if a_idx == 0:
                alarm.alarm_time = f"{tw_h:02d}:{tw_m:02d}"
                alarm.title = f"{u.name.split()[0]}'s {random.choice(alarm_title_bank)}"
                alarm.alarm_type = "Weekday" if random.random() < 0.7 else "Daily"
                alarm.repeat_days = "Mon,Tue,Wed,Thu,Fri" if alarm.alarm_type == "Weekday" else "Mon,Tue,Wed,Thu,Fri,Sat,Sun"
                alarm.is_active = True
                alarm.challenge = challenge_types[(idx + a_idx) % len(challenge_types)]
                alarm.difficulty_level = difficulties[(idx + a_idx) % len(difficulties)]
                alarm.verification_method = verification_methods[(idx + a_idx) % len(verification_methods)]
                alarm.verification_steps = 3 if alarm.verification_method == "multi_step" else 1
                alarm.snooze_duration = random.choice([5, 8, 10])
                alarm.max_snoozes = random.choice([2, 3, 4])
            # Alarm 2: Secondary / Workout / Study alarm (mixed Active/Inactive)
            elif a_idx == 1:
                sec_h = (tw_h + random.choice([1, 2])) % 24
                sec_m = random.choice([0, 15, 30, 45])
                alarm.alarm_time = f"{sec_h:02d}:{sec_m:02d}"
                alarm.title = random.choice(alarm_title_bank)
                alarm.alarm_type = random.choice(["Daily", "Custom", "Weekday"])
                alarm.repeat_days = random.choice(["Mon,Wed,Fri", "Tue,Thu", "Mon,Tue,Wed,Thu,Fri"])
                alarm.is_active = (a_idx % 2 == 0) or (random.random() < 0.6)
                alarm.challenge = challenge_types[(idx + 2) % len(challenge_types)]
                alarm.difficulty_level = random.choice(["Easy", "Medium", "Hard"])
                alarm.verification_method = random.choice(verification_methods)
            # Alarm 3: Weekend or Leisure (Mixed)
            else:
                we_h = (tw_h + random.choice([2, 3])) % 24
                alarm.alarm_time = f"{we_h:02d}:{random.choice([0, 30]):02d}"
                alarm.title = "Weekend Leisure Awakening" if random.random() < 0.5 else "Mindfulness Routine"
                alarm.alarm_type = "Weekend"
                alarm.repeat_days = "Sat,Sun"
                alarm.is_active = random.random() < 0.5
                alarm.challenge = random.choice(challenge_types)
                alarm.difficulty_level = random.choice(["Beginner", "Easy", "Medium"])
                alarm.verification_method = random.choice(verification_methods)

            db.add(alarm)
    db.commit()
    print("Diversified all alarms with mixed titles, times, active states, challenge types, and methods.")

    # 3. Diversify Challenge Attempts across the last 30 days
    # Clear old identical challenge attempts and regenerate varied realistic interaction histories
    db.query(ChallengeAttempt).delete()
    db.commit()

    total_attempts_created = 0
    for idx, u in enumerate(users):
        c_profile = chronotypes[idx % len(chronotypes)]
        u_alarms = db.query(Alarm).filter(Alarm.user_id == u.id, Alarm.is_active == True).all()
        primary_alarm = u_alarms[0] if u_alarms else None
        
        tw_h, tw_m = map(int, (u.target_wake_time or "07:00").split(":"))
        accuracy_rate = c_profile["accuracy"]
        
        # Create 14 to 28 days of distinct challenge logs
        days_history = random.randint(14, 28)
        for day_offset in range(1, days_history + 1):
            day_base = now - timedelta(days=day_offset)
            
            # Wake delay jitter: some on-time, some 2m early, some 8m late
            wake_jitter = random.randint(-4, 18)
            wake_time = day_base.replace(hour=tw_h, minute=tw_m, second=random.randint(0, 50)) + timedelta(minutes=wake_jitter)
            
            # Decide if attempt succeeded based on user's specific accuracy profile
            is_pass = random.random() < accuracy_rate
            c_type = random.choice(challenge_types)
            diff = random.choice(difficulties)
            q_list = sample_questions.get(c_type, sample_questions["Math Problems"])
            q_item = random.choice(q_list)
            
            time_taken = random.randint(4, 16) if is_pass else random.randint(15, 20)
            wake_rating = random.randint(4, 5) if (is_pass and wake_jitter <= 5) else (random.randint(2, 3) if is_pass else random.randint(1, 2))
            
            attempt = ChallengeAttempt(
                user_id=u.id,
                alarm_id=primary_alarm.id if primary_alarm else None,
                challenge_type=c_type,
                difficulty=diff,
                question=q_item[0],
                correct_answer=q_item[1],
                user_answer=q_item[1] if is_pass else "Err",
                is_correct=is_pass,
                attempt_number=1 if is_pass else random.randint(1, 2),
                time_taken=time_taken,
                time_limit=20,
                verification_status="passed" if is_pass else ("timeout" if time_taken >= 20 else "failed"),
                session_id=f"sess_{u.id}_{day_base.strftime('%Y%m%d')}_{int(wake_time.timestamp())}",
                wakefulness_rating=wake_rating,
                completed_at=wake_time + timedelta(seconds=time_taken),
                created_at=wake_time
            )
            db.add(attempt)
            total_attempts_created += 1

    db.commit()
    print(f"Generated {total_attempts_created} diverse and non-uniform challenge attempts across 30 days.")

    # 4. Diversify Snooze Events
    db.query(AlarmSnoozeEvent).delete()
    db.commit()

    total_snoozes = 0
    for idx, u in enumerate(users):
        u_alarms = db.query(Alarm).filter(Alarm.user_id == u.id).all()
        if not u_alarms:
            continue
        
        # Chronotype determines snooze tendency (e.g. Night Owls snooze more than Early Birds)
        snooze_frequency = 0 if idx % 4 == 0 else (1 if idx % 4 in (1, 2) else 3)
        for _ in range(snooze_frequency):
            s_day = now - timedelta(days=random.randint(1, 14), hours=random.randint(6, 9))
            count = random.randint(1, 3)
            snooze = AlarmSnoozeEvent(
                user_id=u.id,
                alarm_id=random.choice(u_alarms).id,
                snooze_count=count,
                scheduled_for=s_day + timedelta(minutes=5 * count),
                created_at=s_day
            )
            db.add(snooze)
            total_snoozes += 1

    db.commit()
    print(f"Generated {total_snoozes} realistic mixed snooze events across users.")

    db.close()
    print("PostgreSQL database successfully diversified with mixed, realistic, non-identical data!")


if __name__ == "__main__":
    mix_up_database_data()
