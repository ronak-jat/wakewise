/* ==========================================================================
   INTELLIGENT COGNITIVE ALARM PLATFORM - USER PORTAL CONTROLLER
   ========================================================================== */

// 1. Data Store / State Managers
let alarms = [];
let alarmMonitorInterval = null;
let alarmTriggerCache = new Set();
// API Base URL is globally configured in window.API_BASE_URL


function getAuthHeaders() {
    let token = '';
    try {
        const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
        token = session.accessToken || session.token || localStorage.getItem('token') || localStorage.getItem('accessToken') || '';
    } catch (_) {}

    return {
        'Content-Type': 'application/json',
        'Authorization': token ? `Bearer ${token}` : '',
        'X-Timezone-Offset': String(-new Date().getTimezoneOffset()),
        'X-Timezone': (Intl && Intl.DateTimeFormat) ? Intl.DateTimeFormat().resolvedOptions().timeZone : 'Asia/Kolkata'
    };
}

async function fetchAlarmsFromServer() {
    try {
        const response = await fetch(`${window.API_BASE_URL}/api/alarms/`, {
            method: 'GET',
            headers: getAuthHeaders()
        });
        if (response.ok) {
            alarms = await response.json();
            renderAlarms();
            startAlarmMonitor();
        } else {
            console.error('Failed to fetch alarms from server:', response.status);
            renderAlarms();
        }
    } catch (e) {
        console.error('Network error fetching alarms:', e);
        renderAlarms();
    }
}

function getChallengeLabel(challenge) {
    if (challenge === 'math') return 'Math Formulas';
    if (challenge === 'tap') return 'Precision Taps';
    if (challenge === 'none') return 'None';
    return challenge || 'None';
}

function getSoundUrl() {
    return window.location.pathname.includes('/user/') ? '../assets/sounds/radar.mp3' : '/assets/sounds/radar.mp3';
}

function getAlarmAudioElement() {
    let audio = document.getElementById('alarm-audio');
    if (!audio) {
        audio = document.createElement('audio');
        audio.id = 'alarm-audio';
        audio.loop = true;
        audio.preload = 'auto';
        document.body.appendChild(audio);
    }
    if (!audio.src || audio.src === '' || audio.src.endsWith('/')) {
        audio.src = getSoundUrl();
    }
    return audio;
}

// Global Audio Engine State
window.WakeWiseAudioContext = null;
window.radarAudioBuffer = null;
window.activeWebAudioSource = null;
let synthPulseInterval = null;

// Initialize and resume AudioContext on user interaction
async function initWakeWiseAudio() {
    try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;
        if (!window.WakeWiseAudioContext) {
            window.WakeWiseAudioContext = new AudioContextClass();
        }
        if (window.WakeWiseAudioContext.state === 'suspended') {
            await window.WakeWiseAudioContext.resume();
        }

        // Pre-fetch & decode radar.mp3 for buffer playback
        if (!window.radarAudioBuffer) {
            try {
                const soundUrl = getSoundUrl();
                const res = await fetch(soundUrl);
                if (res.ok) {
                    const arrayBuf = await res.arrayBuffer();
                    window.WakeWiseAudioContext.decodeAudioData(arrayBuf, (decoded) => {
                        window.radarAudioBuffer = decoded;
                        console.log('[AUDIO] radar.mp3 pre-decoded into Web Audio buffer.');
                    }, (err) => {
                        console.warn('[AUDIO] decodeAudioData note:', err);
                    });
                }
            } catch (fetchErr) {
                console.warn('[AUDIO] Failed to fetch radar.mp3 buffer:', fetchErr);
            }
        }

        // Pre-prime HTML5 audio element
        const audio = getAlarmAudioElement();
        if (audio) {
            audio.muted = false;
            audio.volume = 1.0;
        }
    } catch (e) {
        console.warn('[AUDIO] initWakeWiseAudio note:', e);
    }
}

// Attach gesture listener to prime audio on any user action
['click', 'keydown', 'touchstart'].forEach(evt => {
    document.addEventListener(evt, initWakeWiseAudio, { passive: true });
});

// Web Audio API synthesizer pulse fallback
function playSynthesizerBeep() {
    try {
        const ctx = window.WakeWiseAudioContext || new (window.AudioContext || window.webkitAudioContext)();
        if (!ctx) return;
        if (ctx.state === 'suspended') {
            ctx.resume().catch(() => {});
        }
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, ctx.currentTime);
        gain.gain.setValueAtTime(0.4, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.8);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.8);
    } catch (e) {
        console.warn('[AUDIO] Synthesizer pulse note:', e);
    }
}

function playWebAudioBufferOrBeep() {
    if (window.WakeWiseAudioContext) {
        if (window.WakeWiseAudioContext.state === 'suspended') {
            window.WakeWiseAudioContext.resume().catch(() => {});
        }
        if (window.radarAudioBuffer) {
            try {
                if (window.activeWebAudioSource) {
                    try { window.activeWebAudioSource.stop(); } catch (_) {}
                }
                const srcNode = window.WakeWiseAudioContext.createBufferSource();
                srcNode.buffer = window.radarAudioBuffer;
                srcNode.loop = true;
                const gainNode = window.WakeWiseAudioContext.createGain();
                gainNode.gain.value = 1.0;
                srcNode.connect(gainNode);
                gainNode.connect(window.WakeWiseAudioContext.destination);
                srcNode.start(0);
                window.activeWebAudioSource = srcNode;
                console.log("🔊 ALARM AUDIO PLAYING SUCCESSFULLY (Web Audio Buffer)");
                return;
            } catch (err) {
                console.warn('[AUDIO] Web Audio Buffer play note:', err);
            }
        }
    }
    // Fallback to synthesizer pulse
    if (!synthPulseInterval) {
        synthPulseInterval = setInterval(playSynthesizerBeep, 1500);
        playSynthesizerBeep();
    }
}

window.testAlarmSound = async function() {
    await initWakeWiseAudio();
    Toast.show('Testing Alarm Sound', 'Playing radar alarm tone for 3 seconds...', 'info', 3500);
    const audio = getAlarmAudioElement();
    let testPlayed = false;
    if (audio) {
        audio.muted = false;
        audio.volume = 1.0;
        audio.currentTime = 0;
        try {
            await audio.play();
            testPlayed = true;
            setTimeout(() => {
                audio.pause();
                audio.currentTime = 0;
            }, 3000);
        } catch (_) {}
    }
    if (!testPlayed) {
        playWebAudioBufferOrBeep();
        setTimeout(() => {
            if (window.activeWebAudioSource) {
                try { window.activeWebAudioSource.stop(); } catch (_) {}
                window.activeWebAudioSource = null;
            }
            if (synthPulseInterval) {
                clearInterval(synthPulseInterval);
                synthPulseInterval = null;
            }
        }, 3000);
    }
};

window.stopAlarmSound = () => {
    const audio = getAlarmAudioElement();
    if (audio) {
        audio.pause();
        audio.currentTime = 0;
    }
    if (window.activeWebAudioSource) {
        try {
            window.activeWebAudioSource.stop();
        } catch (_) {}
        window.activeWebAudioSource = null;
    }
    if (synthPulseInterval) {
        clearInterval(synthPulseInterval);
        synthPulseInterval = null;
    }
    currentRingingAlarm = null;
    activeCognitiveChallenge = null;
    selectedChallengeOption = null;
    stopChallengeTimer();
};

// Wake-Up Verification Session State
window.isWakeUpVerified = false;
let currentVerificationState = {
    sessionId: null,
    status: 'in_progress', // pending, in_progress, passed, failed, timeout
    method: 'puzzle_completion',
    currentStep: 1,
    totalSteps: 1,
    correctCount: 0,
    requiredAccuracy: 100,
    consecutiveCorrect: 0,
    consecutiveRequired: 1,
    timeLimit: 20,
    timeRemaining: 20
};

function renderVerificationHUD(state) {
    if (!state) state = currentVerificationState;

    // 1. Status Badge
    const statusBadge = document.getElementById('verification-status-badge');
    if (statusBadge) {
        statusBadge.className = `verification-status-badge status-${state.status || 'in_progress'}`;
        if (state.status === 'in_progress') {
            statusBadge.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> In Progress';
        } else if (state.status === 'passed') {
            statusBadge.innerHTML = '<i class="fas fa-check-circle"></i> Passed';
        } else if (state.status === 'failed') {
            statusBadge.innerHTML = '<i class="fas fa-times-circle"></i> Failed';
        } else if (state.status === 'timeout') {
            statusBadge.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Timeout';
        } else {
            statusBadge.innerHTML = '<i class="fas fa-clock"></i> Pending';
        }
    }

    // 2. Progress
    const progressVal = document.getElementById('hud-progress-val');
    const progressBar = document.getElementById('hud-progress-bar');
    const currStep = state.currentStep || 1;
    const totSteps = state.totalSteps || 1;
    if (progressVal) {
        progressVal.textContent = `${currStep}/${totSteps}`;
    }
    if (progressBar) {
        const pct = Math.min(100, Math.round((currStep / totSteps) * 100));
        progressBar.style.width = `${pct}%`;
    }

    // 3. Correct Answers
    const correctVal = document.getElementById('hud-correct-val');
    if (correctVal) {
        correctVal.textContent = state.correctCount || 0;
    }

    // 4. Required Accuracy
    const accuracyVal = document.getElementById('hud-accuracy-val');
    if (accuracyVal) {
        if (state.method === 'accuracy_check' || state.method === 'multi_step') {
            const minNeeded = Math.ceil(((state.requiredAccuracy || 67) / 100) * totSteps);
            accuracyVal.textContent = `${minNeeded}/${totSteps} (${state.requiredAccuracy || 67}%)`;
        } else if (state.method === 'consecutive_correct') {
            accuracyVal.textContent = `Streak: ${state.consecutiveRequired || 2} in a row`;
        } else {
            accuracyVal.textContent = `1/1 (100%)`;
        }
    }

    // 5. Consecutive Correct
    const consecutiveVal = document.getElementById('hud-consecutive-val');
    if (consecutiveVal) {
        consecutiveVal.textContent = `${state.consecutiveCorrect || 0}/${state.consecutiveRequired || 1}`;
    }

    // 6. Time Remaining
    const timerDisplay = document.getElementById('challenge-timer-display');
    if (timerDisplay && state.timeRemaining !== undefined) {
        timerDisplay.textContent = `${state.timeRemaining}s`;
    }
}

function triggerAlarmSound(alarm) {
    if (!alarm) return;

    resetChallengeModalDisplay();

    // Prevent duplicate triggers if an alarm is already actively ringing
    if (currentRingingAlarm) {
        console.log("⚠️ Alarm already ringing. Ignoring duplicate trigger for:", alarm.title || alarm.id);
        return;
    }

    currentRingingAlarm = alarm;
    window.isWakeUpVerified = false;

    console.log(`[AUDIO] Sound playback attempted for alarm ID: ${alarm.id}, Sound: ${alarm.sound || 'Radar'}`);
    console.log("🔔 ALARM TRIGGERED:", alarm.title || alarm.id);

    // Extract or default verification configuration (Default to 3-question Multi-Step)
    let vMethod = alarm.verification_method;
    if (!vMethod || vMethod === 'puzzle_completion' || vMethod === 'none' || vMethod === '') {
        vMethod = 'multi_step';
    }
    let vSteps = parseInt(alarm.verification_steps) || 3;
    let reqAcc = alarm.required_accuracy ? parseFloat(alarm.required_accuracy) : 67;
    let consecReq = alarm.consecutive_required ? parseInt(alarm.consecutive_required) : 2;
    let timeLim = alarm.time_limit ? parseInt(alarm.time_limit) : 20;

    if (vMethod === 'multi_step') {
        vSteps = Math.max(3, vSteps || 3);
        reqAcc = reqAcc || 67;
    } else if (vMethod === 'consecutive_correct') {
        consecReq = Math.max(2, consecReq || 2);
        vSteps = consecReq;
    } else if (vMethod === 'accuracy_check') {
        vSteps = Math.max(3, vSteps || 3);
        reqAcc = reqAcc || 67;
    } else if (vMethod === 'time_based') {
        timeLim = Math.min(30, Math.max(5, timeLim || 15));
    }

    currentVerificationState = {
        sessionId: null,
        status: 'in_progress',
        method: vMethod,
        currentStep: 1,
        totalSteps: vSteps,
        correctCount: 0,
        requiredAccuracy: reqAcc,
        consecutiveCorrect: 0,
        consecutiveRequired: consecReq,
        timeLimit: timeLim,
        timeRemaining: timeLim
    };

    const audio = getAlarmAudioElement();
    if (audio) {
        audio.loop = true;
        audio.volume = 1.0;
        audio.muted = false;
        audio.currentTime = 0;

        audio.play()
            .then(() => {
                console.log("🔊 ALARM AUDIO PLAYING SUCCESSFULLY (HTML5 Audio)");
            })
            .catch(error => {
                console.warn("⚠️ HTML5 Audio.play() restricted or delayed:", error.name, error.message);
                playWebAudioBufferOrBeep();

                Toast.show(
                    'Alarm Ringing',
                    'Click anywhere on the screen to maximize alarm volume.',
                    'warning',
                    6000
                );

                const unlockAudio = async () => {
                    try {
                        await initWakeWiseAudio();
                        audio.currentTime = 0;
                        audio.loop = true;
                        audio.muted = false;
                        audio.volume = 1.0;
                        await audio.play();
                        console.log("🔊 ALARM AUDIO UNLOCKED AND PLAYING");
                        if (synthPulseInterval) {
                            clearInterval(synthPulseInterval);
                            synthPulseInterval = null;
                        }
                        if (window.activeWebAudioSource) {
                            try { window.activeWebAudioSource.stop(); } catch (_) {}
                            window.activeWebAudioSource = null;
                        }
                        document.removeEventListener('click', unlockAudio);
                        document.removeEventListener('keydown', unlockAudio);
                        document.removeEventListener('touchstart', unlockAudio);
                    } catch (err) {
                        console.error("❌ Audio still blocked:", err);
                    }
                };

                document.addEventListener('click', unlockAudio);
                document.addEventListener('keydown', unlockAudio);
                document.addEventListener('touchstart', unlockAudio);
            });
    } else {
        playWebAudioBufferOrBeep();
    }

    // Render HUD and start verification session
    renderVerificationHUD(currentVerificationState);

    const chType = alarm.challenge_type || (typeof alarm.challenge === 'string' && alarm.challenge !== 'none' ? alarm.challenge : 'Math Problems');
    const diff = alarm.difficulty || alarm.difficulty_level || 'Medium';

    fetch(`${window.API_BASE_URL}/api/challenges/verification/start`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
            alarm_id: alarm.id || null,
            challenge_type: chType,
            difficulty: diff,
            verification_method: vMethod,
            verification_steps: vSteps,
            required_accuracy: reqAcc,
            consecutive_required: consecReq,
            time_limit: timeLim,
            first_challenge: alarm.challenge && typeof alarm.challenge === 'object' ? alarm.challenge : null
        })
    })
    .then(res => res.json())
    .then(data => {
        currentVerificationState.sessionId = data.session_id;
        currentVerificationState.status = data.status || 'in_progress';
        currentVerificationState.currentStep = data.current_step || 1;
        currentVerificationState.totalSteps = data.total_steps || vSteps;
        currentVerificationState.correctCount = data.correct_count || 0;
        currentVerificationState.requiredAccuracy = data.required_accuracy || reqAcc;
        currentVerificationState.consecutiveCorrect = data.consecutive_correct || 0;
        currentVerificationState.consecutiveRequired = data.consecutive_required || consecReq;
        currentVerificationState.timeLimit = data.time_limit || timeLim;
        currentVerificationState.timeRemaining = data.time_limit || timeLim;

        renderVerificationHUD(currentVerificationState);

        if (data.current_challenge) {
            displayCognitiveChallenge(data.current_challenge, 1);
        } else if (alarm.challenge && typeof alarm.challenge === 'object' && alarm.challenge.question) {
            displayCognitiveChallenge(alarm.challenge, 1);
        } else {
            displayCognitiveChallenge({
                type: chType,
                difficulty: diff,
                question: 'What is 15 + 28?',
                options: ['33', '43', '45', '53'],
                answer: '43',
                explanation: '15 + 28 = 43.'
            }, 1);
        }
    })
    .catch(err => {
        console.error('Error starting verification session:', err);
        renderVerificationHUD(currentVerificationState);
        displayCognitiveChallenge({
            type: chType,
            difficulty: diff,
            question: 'What is 15 + 28?',
            options: ['33', '43', '45', '53'],
            answer: '43',
            explanation: '15 + 28 = 43.'
        }, 1);
    });

    Toast.show(
        'Wake-Up Verification',
        `${alarm.title || 'Alarm'} is ringing! Complete the verification to silence it.`,
        'warning',
        10000
    );
}

let currentAttemptNumber = 1;
let challengeStartTime = 0;
let challengeTimerInterval = null;
let verificationRequestInFlight = false;

function resetChallengeModalDisplay() {
    const challengeQuestion = document.getElementById('challenge-question');
    const challengeOptions = document.getElementById('challenge-options-container');
    const challengeInput = document.getElementById('challenge-input-group');
    const submitButton = document.getElementById('submit-challenge-btn');
    const challengeFeedback = document.getElementById('challenge-feedback');
    const wakefulnessPanel = document.getElementById('wakefulness-panel');

    if (wakefulnessPanel) wakefulnessPanel.remove();
    if (challengeQuestion) challengeQuestion.style.display = 'block';
    if (challengeOptions) challengeOptions.style.display = 'flex';
    if (challengeInput) challengeInput.style.display = 'block';
    if (submitButton) submitButton.style.display = 'inline-block';
    if (challengeFeedback) {
        challengeFeedback.textContent = '';
        challengeFeedback.style.color = '';
    }
}

function showWakefulnessScreen() {
    stopChallengeTimer();
    const modal = document.querySelector('#challenge-modal .modal-container');
    if (!modal) return;
    const challengeQuestion = document.getElementById('challenge-question');
    const challengeOptions = document.getElementById('challenge-options-container');
    const challengeInput = document.getElementById('challenge-input-group');
    const submitButton = document.getElementById('submit-challenge-btn');
    const challengeFeedback = document.getElementById('challenge-feedback');
    if (challengeQuestion) challengeQuestion.style.display = 'none';
    if (challengeOptions) challengeOptions.style.display = 'none';
    if (challengeInput) challengeInput.style.display = 'none';
    if (submitButton) submitButton.style.display = 'none';
    if (challengeFeedback) {
        challengeFeedback.textContent = '';
        challengeFeedback.style.color = '';
    }

    let panel = document.getElementById('wakefulness-panel');
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'wakefulness-panel';
        panel.style.cssText = 'text-align:center;padding:18px 8px;';
        modal.querySelector('.modal-body').appendChild(panel);
    }
    panel.innerHTML = `
        <h3>How awake do you feel?</h3>
        <div id="wakefulness-ratings" style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin:18px 0 8px;">
            ${['1 - Very sleepy', '2 - Sleepy', '3 - Somewhat awake', '4 - Awake', '5 - Fully awake'].map((label, index) => `<button type="button" class="btn btn-secondary wakefulness-rating" data-rating="${index + 1}">${label}</button>`).join('')}
        </div>
        <button type="button" class="btn btn-primary" id="submit-wakefulness-btn" disabled>Submit rating</button>
        <div id="wakefulness-feedback" style="margin-top:10px;"></div>`;
    panel.style.display = 'block';
    let selectedRating = null;
    panel.querySelectorAll('.wakefulness-rating').forEach(button => {
        button.addEventListener('click', () => {
            selectedRating = Number(button.dataset.rating);
            panel.querySelectorAll('.wakefulness-rating').forEach(item => item.classList.remove('btn-primary'));
            button.classList.add('btn-primary');
            panel.querySelector('#submit-wakefulness-btn').disabled = false;
        });
    });
    panel.querySelector('#submit-wakefulness-btn').addEventListener('click', async () => {
        const alarm = currentRingingAlarm;
        const feedback = panel.querySelector('#wakefulness-feedback');
        try {
            const response = await fetch(`${window.API_BASE_URL}/api/alarms/${alarm.id}/wakefulness`, {
                method: 'POST', headers: getAuthHeaders(),
                body: JSON.stringify({ rating: selectedRating, session_id: currentVerificationState.sessionId })
            });
            if (!response.ok) throw new Error('Wakefulness rating could not be saved');
            showAlarmActionScreen();
        } catch (error) {
            feedback.textContent = error.message;
            feedback.style.color = 'var(--color-danger)';
        }
    });
}

function showAlarmActionScreen() {
    const challengeQuestion = document.getElementById('challenge-question');
    const challengeOptions = document.getElementById('challenge-options-container');
    const challengeInput = document.getElementById('challenge-input-group');
    const submitButton = document.getElementById('submit-challenge-btn');
    if (challengeQuestion) challengeQuestion.style.display = 'none';
    if (challengeOptions) challengeOptions.style.display = 'none';
    if (challengeInput) challengeInput.style.display = 'none';
    if (submitButton) submitButton.style.display = 'none';

    const panel = document.getElementById('wakefulness-panel');
    if (!panel || !currentRingingAlarm) return;
    const alarm = currentRingingAlarm;
    const snoozeCount = Number(alarm.snooze_count || 0);
    const maxSnoozes = Number(alarm.max_snoozes ?? 3);
    panel.innerHTML = `<h3>You're awake! What would you like to do?</h3>
        <div style="display:flex;gap:10px;justify-content:center;margin-top:18px;flex-wrap:wrap;">
            <button type="button" class="btn btn-primary" id="dismiss-alarm-btn">Dismiss Alarm</button>
            <button type="button" class="btn btn-secondary" id="snooze-alarm-btn" ${snoozeCount >= maxSnoozes ? 'disabled' : ''}>Snooze ${alarm.snooze_duration || 5} min</button>
        </div><div id="alarm-action-feedback" style="margin-top:10px;"></div>`;
    panel.querySelector('#dismiss-alarm-btn').addEventListener('click', async () => {
        const sessionId = currentVerificationState.sessionId;
        const response = await fetch(`${window.API_BASE_URL}/api/alarms/${alarm.id}/dismiss`, {
            method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ session_id: sessionId })
        });
        if (!response.ok) return;
        stopAlarmSound();
        Modal.close('challenge-modal');
        fetchAlarmsFromServer();
    });
    const snoozeButton = panel.querySelector('#snooze-alarm-btn');
    if (snoozeButton && !snoozeButton.disabled) {
        snoozeButton.addEventListener('click', async () => {
            const response = await fetch(`${window.API_BASE_URL}/api/alarms/${alarm.id}/snooze`, {
                method: 'POST', headers: getAuthHeaders(),
                body: JSON.stringify({ session_id: currentVerificationState.sessionId, snooze_count: snoozeCount })
            });
            if (!response.ok) return;
            stopAlarmSound();
            Modal.close('challenge-modal');
            fetchAlarmsFromServer();
        });
    }
}

function startChallengeTimer(timeLimitSeconds) {
    if (challengeTimerInterval) {
        clearInterval(challengeTimerInterval);
        challengeTimerInterval = null;
    }

    const limit = timeLimitSeconds || currentVerificationState.timeLimit || 20;
    challengeStartTime = Date.now();
    let secondsLeft = limit;
    currentVerificationState.timeRemaining = secondsLeft;

    const timerBanner = document.getElementById('challenge-timer-container');
    const timerDisplay = document.getElementById('challenge-timer-display');

    const updateTimerUI = () => {
        if (timerDisplay) {
            timerDisplay.textContent = `${secondsLeft}s`;
        }
        if (timerBanner) {
            if (secondsLeft <= 5) {
                timerBanner.classList.add('timer-critical');
                if (timerDisplay) timerDisplay.style.color = '#ef4444';
            } else if (secondsLeft <= 10) {
                timerBanner.classList.remove('timer-critical');
                if (timerDisplay) timerDisplay.style.color = '#f59e0b';
            } else {
                timerBanner.classList.remove('timer-critical');
                if (timerDisplay) timerDisplay.style.color = '#10b981';
            }
        }
    };

    updateTimerUI();

    challengeTimerInterval = setInterval(async () => {
        secondsLeft--;
        currentVerificationState.timeRemaining = secondsLeft;
        updateTimerUI();

        if (secondsLeft <= 0) {
            clearInterval(challengeTimerInterval);
            challengeTimerInterval = null;
            await handleChallengeTimeout();
        }
    }, 1000);
}

function stopChallengeTimer() {
    if (challengeTimerInterval) {
        clearInterval(challengeTimerInterval);
        challengeTimerInterval = null;
    }
}

async function handleChallengeTimeout() {
    if (verificationRequestInFlight) return;
    verificationRequestInFlight = true;
    const timeTaken = Math.round((Date.now() - challengeStartTime) / 1000);
    const feedback = document.getElementById('challenge-feedback');

    currentVerificationState.status = 'timeout';
    currentVerificationState.consecutiveCorrect = 0; // Streak reset on timeout
    renderVerificationHUD(currentVerificationState);

    const modalContainer = document.querySelector('#challenge-modal .modal-container');
    if (modalContainer) {
        modalContainer.classList.add('challenge-shake');
        setTimeout(() => modalContainer.classList.remove('challenge-shake'), 600);
    }

    try {
        const response = await fetch(`${window.API_BASE_URL}/api/challenges/verification/step`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                session_id: currentVerificationState.sessionId || (activeCognitiveChallenge ? activeCognitiveChallenge.id : ''),
                step_number: currentVerificationState.currentStep,
                challenge_id: activeCognitiveChallenge ? activeCognitiveChallenge.id : null,
                user_answer: '',
                time_taken: timeTaken,
                is_timeout: true,
                alarm_id: currentRingingAlarm ? currentRingingAlarm.id : null
            })
        });

        if (response.ok) {
            const resData = await response.json();
            currentAttemptNumber++;

            currentVerificationState.status = resData.verification_status;
            currentVerificationState.currentStep = resData.current_step;
            currentVerificationState.totalSteps = resData.total_steps;
            currentVerificationState.correctCount = resData.correct_count;
            currentVerificationState.consecutiveCorrect = resData.consecutive_correct;
            currentVerificationState.consecutiveRequired = resData.consecutive_required;
            renderVerificationHUD(currentVerificationState);

            if (resData.next_challenge) {
                displayCognitiveChallenge(resData.next_challenge, currentAttemptNumber);
                if (feedback) {
                    feedback.style.color = '#ef4444';
                    feedback.textContent = resData.message || '⏱️ Time expired! Attempt recorded as timed out. Solve this new question:';
                }
            } else {
                if (feedback) {
                    feedback.style.color = '#ef4444';
                    feedback.textContent = '⏱️ Time expired! Attempt recorded. Retrying...';
                }
                startChallengeTimer(currentVerificationState.timeLimit || 20);
            }
            Toast.show('Time Expired', 'Attempt recorded as timed out. Solve new challenge!', 'danger', 3000);
        }
    } catch (err) {
        console.error('Error handling challenge timeout:', err);
    } finally {
        verificationRequestInFlight = false;
    }
}

function displayCognitiveChallenge(challenge, attemptNum = 1) {
    activeCognitiveChallenge = challenge;
    selectedChallengeOption = null;
    currentAttemptNumber = attemptNum || 1;

    if (memoryTimer) {
        clearInterval(memoryTimer);
        memoryTimer = null;
    }

    const typeBadge = document.getElementById('challenge-type-badge');
    const diffBadge = document.getElementById('challenge-difficulty-badge');
    const attemptBadge = document.getElementById('challenge-attempt-badge');
    const questionElem = document.getElementById('challenge-question');
    const subtitleElem = document.getElementById('challenge-subtitle');
    const optionsContainer = document.getElementById('challenge-options-container');
    const inputGroup = document.getElementById('challenge-input-group');
    const answerInput = document.getElementById('challenge-answer');
    const feedbackElem = document.getElementById('challenge-feedback');

    if (typeBadge) typeBadge.textContent = challenge.type || 'Math Problems';
    if (diffBadge) {
        diffBadge.textContent = challenge.difficulty || 'Medium';
        diffBadge.className = `badge ${challenge.difficulty === 'Beginner' || challenge.difficulty === 'Easy' ? 'badge-success' : challenge.difficulty === 'Difficult' || challenge.difficulty === 'Advanced' || challenge.difficulty === 'Hard' || challenge.difficulty === 'Expert' ? 'badge-danger' : 'badge-warning'}`;
    }
    if (attemptBadge) attemptBadge.textContent = `Attempt ${currentAttemptNumber}`;

    if (feedbackElem) {
        feedbackElem.textContent = '';
        feedbackElem.style.color = '';
    }

    if (answerInput) answerInput.value = '';

    renderVerificationHUD(currentVerificationState);

    // Handle Memory Challenge timing behavior
    const isMemoryChallenge = (challenge.type === 'Memory Challenges' || (challenge.question && challenge.question.toLowerCase().includes('memorize')));

    if (isMemoryChallenge && challenge.question.includes('. What')) {
        const parts = challenge.question.split('. What');
        const memorizeText = parts[0];
        const recallQuestion = 'What' + parts[1];

        if (subtitleElem) subtitleElem.textContent = 'Memorize the items! List will disappear in 5 seconds...';
        if (questionElem) questionElem.textContent = memorizeText;

        if (optionsContainer) optionsContainer.style.display = 'none';
        if (inputGroup) inputGroup.style.display = 'none';

        let countdown = 5;
        memoryTimer = setInterval(() => {
            countdown--;
            if (subtitleElem) subtitleElem.textContent = `Memorize the items! Disappearing in ${countdown}s...`;
            if (countdown <= 0) {
                clearInterval(memoryTimer);
                memoryTimer = null;
                if (subtitleElem) subtitleElem.textContent = 'Recall time! Choose or type the correct item:';
                if (questionElem) questionElem.textContent = recallQuestion;
                renderChallengeControls(challenge, optionsContainer, inputGroup);

                const timeLimit = challenge.time_limit || currentVerificationState.timeLimit || 20;
                startChallengeTimer(timeLimit);
            }
        }, 1000);
    } else {
        if (subtitleElem) subtitleElem.textContent = 'Solve the challenge to silence the wake-up alarm!';
        if (questionElem) questionElem.textContent = challenge.question;
        renderChallengeControls(challenge, optionsContainer, inputGroup);

        const timeLimit = challenge.time_limit || currentVerificationState.timeLimit || 20;
        startChallengeTimer(timeLimit);
    }

    Modal.open('challenge-modal');
}

function renderChallengeControls(challenge, optionsContainer, inputGroup) {
    if (optionsContainer) optionsContainer.innerHTML = '';

    if (challenge.options && Array.isArray(challenge.options) && challenge.options.length > 0) {
        if (optionsContainer) optionsContainer.style.display = 'flex';
        if (inputGroup) inputGroup.style.display = 'none';

        challenge.options.forEach(opt => {
            const optBtn = document.createElement('button');
            optBtn.type = 'button';
            optBtn.className = 'btn';
            optBtn.style.cssText = 'background: rgba(255,255,255,0.08); color: var(--text-primary); border: 1px solid var(--glass-border); padding: 12px 16px; border-radius: 8px; text-align: left; font-size: 1rem; transition: all 0.2s ease; cursor: pointer; display: flex; align-items: center; justify-content: space-between;';
            optBtn.innerHTML = `<span>${opt}</span><i class="far fa-circle text-muted"></i>`;

            optBtn.addEventListener('click', () => {
                selectedChallengeOption = opt;
                optionsContainer.querySelectorAll('button').forEach(b => {
                    b.style.background = 'rgba(255,255,255,0.08)';
                    b.style.borderColor = 'var(--glass-border)';
                    b.querySelector('i').className = 'far fa-circle text-muted';
                });
                optBtn.style.background = 'rgba(79, 70, 229, 0.25)';
                optBtn.style.borderColor = 'var(--color-primary)';
                optBtn.querySelector('i').className = 'fas fa-check-circle text-success';
            });

            optionsContainer.appendChild(optBtn);
        });
    } else {
        if (optionsContainer) optionsContainer.style.display = 'none';
        if (inputGroup) inputGroup.style.display = 'block';
    }
}

function startAlarmMonitor() {
    if (alarmMonitorInterval) return;

    // Single unified alarm monitor polling backend scheduler queue
    alarmMonitorInterval = setInterval(checkAlarmTriggers, 2000);
    checkAlarmTriggers();
}

async function checkAlarmTriggers() {
    // If an alarm is already ringing, do not poll or trigger another one
    if (currentRingingAlarm) return;

    // Backend Scheduler is the single source of truth for triggered alarms
    try {
        const response = await fetch(`${window.API_BASE_URL}/api/alarms/triggered`, {
            headers: getAuthHeaders()
        });
        if (response.ok) {
            const triggered = await response.json();
            if (Array.isArray(triggered) && triggered.length > 0) {
                console.log(`[ALARM MONITOR] Polled /api/alarms/triggered: received ${triggered.length} triggered alarm(s)`);
                const alarmItem = triggered[0];
                const now = new Date();
                const cacheKey = `alarm-${alarmItem.id}-${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}-${now.getHours()}:${now.getMinutes()}`;
                if (!alarmTriggerCache.has(cacheKey) && !currentRingingAlarm) {
                    alarmTriggerCache.add(cacheKey);
                    console.log(`[ALARM MONITOR] Triggering alarm UI and sound for Alarm ID: ${alarmItem.id} ("${alarmItem.title}")`);
                    triggerAlarmSound(alarmItem);
                }
            }
        }
    } catch (e) {
        // Backend not reachable or no session, keep waiting
    }
}

let challengeHistory = JSON.parse(localStorage.getItem('user_challenges')) || [
    { mode: 'Mental Arithmetic', score: '100% (Pass)', date: 'Today, 07:34 AM' }
];

let notifications = [];

// Tracks daily challenge completion for the progress bar
let dailyChallengeCompleted = false;

// 2. Tab Navigation Switcher
window.switchTab = (tabId) => {
    if (!tabId) return;

    let targetId = tabId;
    if (!document.getElementById(targetId) && document.getElementById(`tab-${tabId}`)) {
        targetId = `tab-${tabId}`;
    }

    // Hide all tabs
    document.querySelectorAll('.tab-content-section').forEach(section => {
        section.classList.remove('active');
    });

    // Show selected tab
    const activeSection = document.getElementById(targetId);
    if (activeSection) {
        activeSection.classList.add('active');
    }

    // Update active sidebar item styling
    document.querySelectorAll('.sidebar-menu-item').forEach(item => {
        item.classList.remove('active');
        const itemTab = item.dataset.tab;
        if (itemTab === targetId || itemTab === tabId || itemTab === targetId.replace('tab-', '')) {
            item.classList.add('active');
        }
    });

    // Update Breadcrumb Text
    const crumbText = document.getElementById('breadcrumb-current');
    if (crumbText) {
        const item = document.querySelector(`.sidebar-menu-item.active span`);
        crumbText.textContent = item ? item.textContent : (targetId === 'tab-profile' ? 'Profile' : 'Dashboard');
    }

    if (targetId === 'tab-profile' && typeof loadUserProfileSettings === 'function') {
        loadUserProfileSettings();
    }

    const cleanHash = targetId.replace('tab-', '');
    if (window.history && window.history.replaceState) {
        window.history.replaceState(null, null, `#${cleanHash}`);
    }

    // Persist active tab state for later page visits
    if (typeof window.setDashboardActiveTab === 'function') {
        window.setDashboardActiveTab(targetId);
    }

    // Close sidebar on mobile after tab switches
    document.body.classList.remove('sidebar-open');
};

const attachDashboardUserEvents = () => {
    document.querySelectorAll('.sidebar-menu-item a').forEach(anchor => {
        anchor.addEventListener('click', (event) => {
            event.preventDefault();
            const item = anchor.closest('.sidebar-menu-item');
            if (!item) return;
            const tabId = item.dataset.tab;
            if (!tabId) return;
            if (typeof window.switchTab === 'function') {
                window.switchTab(tabId);
            }
        });
    });
};

const restoreUserDashboardTab = () => {
    if (typeof window.restoreDashboardActiveTab === 'function') {
        window.restoreDashboardActiveTab();
    }
};

if (document.readyState !== 'loading') {
    attachDashboardUserEvents();
    restoreUserDashboardTab();
} else {
    window.addEventListener('DOMContentLoaded', () => {
        attachDashboardUserEvents();
        restoreUserDashboardTab();
    });
}

// 3. Render Charts
let performanceChart, habitRadarChart, detailedSleepChart;

function initCharts() {
    const isDark = document.body.getAttribute('data-theme') === 'dark';
    const textColor = isDark ? '#9ca3af' : '#62627a';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(99, 102, 241, 0.08)';

    // Weekly Sleep Performance Chart
    const perfCtx = document.getElementById('performanceChart');
    if (perfCtx) {
        performanceChart = new Chart(perfCtx, {
            type: 'line',
            data: {
                labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                datasets: [
                    {
                        label: 'Sleep Hours',
                        data: [7.2, 6.8, 7.5, 8.0, 6.5, 8.5, 9.0],
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.1)',
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'Cognitive Score',
                        data: [85, 78, 90, 95, 80, 88, 92],
                        borderColor: '#06b6d4',
                        backgroundColor: 'rgba(6, 182, 212, 0.1)',
                        fill: true,
                        tension: 0.4,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textColor } }
                },
                scales: {
                    x: { grid: { color: gridColor }, ticks: { color: textColor } },
                    y: { grid: { color: gridColor }, ticks: { color: textColor } },
                    y1: {
                        position: 'right',
                        grid: { drawOnChartArea: false },
                        ticks: { color: textColor }
                    }
                }
            }
        });
    }

    // Habit Radar Chart
    const radarCtx = document.getElementById('habitRadarChart');
    if (radarCtx) {
        habitRadarChart = new Chart(radarCtx, {
            type: 'radar',
            data: {
                labels: ['Cognitive Accuracy', 'Sleep Consistency', 'Hydration Goal', 'Meditation Streak', 'Coach Feedbacks'],
                datasets: [{
                    label: 'User Metric Ratio',
                    data: [92, 85, 70, 60, 90],
                    borderColor: '#a855f7',
                    backgroundColor: 'rgba(168, 85, 247, 0.2)',
                    pointBackgroundColor: '#a855f7'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textColor } }
                },
                scales: {
                    r: {
                        grid: { color: gridColor },
                        pointLabels: { color: textColor },
                        ticks: { display: false }
                    }
                }
            }
        });
    }

    // Detailed Sleep Phases Chart
    const detailedCtx = document.getElementById('detailedSleepChart');
    if (detailedCtx) {
        detailedSleepChart = new Chart(detailedCtx, {
            type: 'bar',
            data: {
                labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                datasets: [
                    {
                        label: 'Deep Sleep (Hrs)',
                        data: [2.1, 1.8, 2.3, 2.5, 1.9, 2.8, 3.0],
                        backgroundColor: '#6366f1'
                    },
                    {
                        label: 'REM Sleep (Hrs)',
                        data: [1.8, 1.6, 2.0, 2.2, 1.5, 2.3, 2.4],
                        backgroundColor: '#a855f7'
                    },
                    {
                        label: 'Light Sleep (Hrs)',
                        data: [3.3, 3.4, 3.2, 3.3, 3.1, 3.4, 3.6],
                        backgroundColor: '#3b82f6'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textColor } }
                },
                scales: {
                    x: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor } },
                    y: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor } }
                }
            }
        });
    }
}

// Watch for theme toggles to adjust chart colors
document.getElementById('theme-toggle')?.addEventListener('click', () => {
    setTimeout(() => {
        if (performanceChart) performanceChart.destroy();
        if (habitRadarChart) habitRadarChart.destroy();
        if (detailedSleepChart) detailedSleepChart.destroy();
        initCharts();
    }, 100);
});
document.querySelector('.nav-toggle-theme')?.addEventListener('click', () => {
    setTimeout(() => {
        if (performanceChart) performanceChart.destroy();
        if (habitRadarChart) habitRadarChart.destroy();
        if (detailedSleepChart) detailedSleepChart.destroy();
        initCharts();
    }, 100);
});

// 4. Progress Bar and Goal Calculations
function updateGoalProgress() {
    let percentage = 75;
    if (window.lastHabitScoreData && typeof window.lastHabitScoreData.habit_score === 'number') {
        percentage = Math.round(window.lastHabitScoreData.habit_score);
    } else {
        const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
        percentage = session.habit_score !== undefined ? Math.round(session.habit_score) : 80;
    }
    percentage = Math.min(100, Math.max(0, percentage));

    const goalBar = document.getElementById('goal-bar');
    const goalPercent = document.getElementById('goal-percent');

    if (goalBar && goalPercent) {
        goalBar.style.width = `${percentage}%`;
        goalPercent.textContent = `${percentage}% Habit Alignment`;

        if (percentage >= 80) {
            goalPercent.className = 'goal-percent-bubble badge-success';
        } else if (percentage >= 50) {
            goalPercent.className = 'goal-percent-bubble';
        } else {
            goalPercent.className = 'goal-percent-bubble badge-warning';
        }
    }
}

// 5. Alarms Table Rendering & Switch Controls
function getAlarmScheduleLabel(alarm) {
    const alarmType = alarm.alarm_type || 'One-Time';
    if (alarmType === 'One-Time') return 'One-Time';
    if (alarmType === 'Daily') return 'Daily';
    if (alarmType === 'Weekdays' || alarmType === 'Weekday') return 'Weekdays';
    if (alarmType === 'Weekends' || alarmType === 'Weekend') return 'Weekends';
    if (alarmType === 'Custom') return alarm.repeat_days ? alarm.repeat_days.split(',').join(', ') : 'Custom';
    if (alarmType === 'Smart Adaptive') return 'Smart Adaptive';
    return alarm.repeat_days ? alarm.repeat_days.split(',').join(', ') : alarmType;
}

function updateCustomDaysVisibility() {
    const alarmType = document.getElementById('alarm-type')?.value;
    const container = document.getElementById('custom-days-container');
    if (container) {
        container.style.display = alarmType === 'Custom' ? 'block' : 'none';
    }
}

function getTbody(elementId) {
    const elem = document.getElementById(elementId);
    if (!elem) return null;
    if (elem.tagName.toLowerCase() === 'tbody') return elem;
    return elem.querySelector('tbody') || elem;
}

function renderAlarms() {
    const alarmsTable = getTbody('alarms-table-body');
    const managerTable = getTbody('alarms-manager-table');

    // Quick metric update
    const activeAlarms = alarms.filter(a => a.is_active);
    const totalAlarmsElem = document.getElementById('stat-total-alarms');
    if (totalAlarmsElem) totalAlarmsElem.textContent = alarms.length;

    const todayAlarmElem = document.getElementById('stat-today-alarm');
    if (todayAlarmElem) {
        const nextActive = activeAlarms[0];
        todayAlarmElem.textContent = nextActive ? `${formatTime12(nextActive.alarm_time)}` : 'None Active';
    }

    if (alarmsTable) {
        alarmsTable.innerHTML = '';
        const activeAlarmsList = alarms.filter(a => a.is_active);
        const displayAlarms = activeAlarmsList.slice(0, 3);

        if (displayAlarms.length === 0) {
            if (alarms.length > 0) {
                alarmsTable.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 20px; color: var(--text-secondary);"><i class="fas fa-toggle-off" style="margin-right: 6px; opacity: 0.6;"></i>No active alarms enabled. <a href="#alarms" onclick="switchTab('tab-alarms')" style="color: var(--color-primary); text-decoration: underline; margin-left: 4px;">Enable alarms in Manager &rarr;</a></td></tr>`;
            } else {
                alarmsTable.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 20px; color: var(--text-secondary);">No alarms configured.</td></tr>`;
            }
        } else {
            displayAlarms.forEach(a => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><strong>${escapeHtml(a.title || 'Alarm')}</strong></td>
                    <td><i class="far fa-clock text-muted" style="margin-right:8px;"></i> ${formatTime12(a.alarm_time)}</td>
                    <td><span class="badge ${a.challenge && a.challenge.toLowerCase() !== 'none' ? 'badge-info' : 'badge-warning'}">${getChallengeLabel(a.challenge)}</span></td>
                    <td><span class="badge badge-success"><i class="fas fa-check-circle" style="margin-right: 3px;"></i> Active</span></td>
                    <td>
                        <label class="switch">
                            <input type="checkbox" ${a.is_active ? 'checked' : ''} onchange="toggleAlarmActive(${a.id})">
                            <span class="slider"></span>
                        </label>
                    </td>
                `;
                alarmsTable.appendChild(tr);
            });
        }
    }

    if (managerTable) {
        managerTable.innerHTML = '';
        if (alarms.length === 0) {
            managerTable.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 24px; color: var(--text-secondary);"><i class="fas fa-clock" style="font-size: 2rem; margin-bottom: 10px; display: block; opacity: 0.5;"></i>No alarms set yet. Click "Set New Alarm" above to create one.</td></tr>`;
        } else {
            alarms.forEach(a => {
                const daysDisplay = getAlarmScheduleLabel(a);
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><strong>${a.title}</strong></td>
                    <td><i class="far fa-clock text-muted"></i> ${formatTime12(a.alarm_time)}</td>
                    <td><span class="badge badge-info">${getChallengeLabel(a.challenge)}</span></td>
                    <td><span style="font-size: 0.8rem; color: var(--text-secondary);">${daysDisplay}</span></td>
                    <td>
                        <label class="switch">
                            <input type="checkbox" ${a.is_active ? 'checked' : ''} onchange="toggleAlarmActive(${a.id})">
                            <span class="slider"></span>
                        </label>
                    </td>
                    <td>
                        <button class="table-action-btn edit-btn" onclick="editAlarm(${a.id})" title="Edit Alarm" style="margin-right:8px; background:var(--color-primary); color:white;"><i class="fas fa-edit"></i></button>
                        <button class="table-action-btn delete-btn" onclick="deleteAlarm(${a.id})" title="Delete Alarm"><i class="fas fa-trash-alt"></i></button>
                    </td>
                `;
                managerTable.appendChild(tr);
            });
        }
    }

    updateGoalProgress();
}

window.toggleAlarmActive = async (id) => {
    const alarm = alarms.find(a => a.id === id);
    if (!alarm) return;
    const action = alarm.is_active ? 'disable' : 'enable';
    try {
        const response = await fetch(`${window.API_BASE_URL}/api/alarms/${id}/${action}`, {
            method: 'PATCH',
            headers: getAuthHeaders()
        });
        if (response.ok) {
            const updated = await response.json();
            alarm.is_active = updated.is_active;
            renderAlarms();
            Toast.show('Alarm Updated', `"${alarm.title}" is now ${alarm.is_active ? 'active' : 'inactive'}.`, 'success', 2000);
        } else {
            Toast.show('Error', 'Failed to update alarm status.', 'danger', 2500);
        }
    } catch (e) {
        console.error('Error toggling alarm active state:', e);
        Toast.show('Error', 'Could not sync update with server.', 'danger', 2500);
    }
};

window.deleteAlarm = async (id) => {
    try {
        const response = await fetch(`${window.API_BASE_URL}/api/alarms/${id}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        if (response.ok) {
            alarms = alarms.filter(a => a.id !== id);
            renderAlarms();
            Toast.show('Alarm Removed', 'The alarm configuration was deleted.', 'danger', 2000);
        } else {
            Toast.show('Error', 'Failed to delete alarm.', 'danger', 2500);
        }
    } catch (e) {
        console.error('Error deleting alarm:', e);
        Toast.show('Error', 'Could not delete alarm.', 'danger', 2500);
    }
};

window.editAlarm = (id) => {
    const alarm = alarms.find(a => a.id === id);
    if (!alarm) return;

    document.getElementById('edit-alarm-id').value = alarm.id;
    document.getElementById('alarm-label').value = alarm.title;
    document.getElementById('alarm-time').value = alarm.alarm_time;
    document.getElementById('alarm-type').value = alarm.alarm_type;
    document.getElementById('alarm-challenge').value = alarm.challenge;
    document.getElementById('alarm-difficulty').value = alarm.difficulty_level || 'Medium';
    document.getElementById('alarm-sound').value = alarm.sound || 'Radar';
    document.getElementById('alarm-vibration').value = alarm.vibration || 'Standard';
    const snoozeDurationElem = document.getElementById('alarm-snooze-duration');
    if (snoozeDurationElem) snoozeDurationElem.value = alarm.snooze_duration || 5;
    const maxSnoozesElem = document.getElementById('alarm-max-snoozes');
    if (maxSnoozesElem) maxSnoozesElem.value = alarm.max_snoozes ?? 3;

    // Verification fields
    const verifMethodElem = document.getElementById('alarm-verification-method');
    if (verifMethodElem) verifMethodElem.value = alarm.verification_method || 'puzzle_completion';
    const verifStepsElem = document.getElementById('alarm-verif-steps');
    if (verifStepsElem) verifStepsElem.value = alarm.verification_steps || 3;
    const verifConsecElem = document.getElementById('alarm-verif-consecutive');
    if (verifConsecElem) verifConsecElem.value = alarm.consecutive_required || 2;
    const verifAccElem = document.getElementById('alarm-verif-accuracy');
    if (verifAccElem) verifAccElem.value = alarm.required_accuracy || 67;
    const verifTimeElem = document.getElementById('alarm-verif-time');
    if (verifTimeElem) verifTimeElem.value = alarm.time_limit || 20;

    updateVerificationFormFields();

    const activeDays = alarm.repeat_days ? alarm.repeat_days.split(',') : [];
    document.querySelectorAll('#custom-days-container input[type="checkbox"]').forEach(cb => {
        cb.checked = activeDays.includes(cb.value);
    });
    updateCustomDaysVisibility();

    const modalTitle = document.getElementById('alarm-modal-title');
    if (modalTitle) modalTitle.textContent = 'Update Cognitive Alarm';

    Modal.open('add-alarm-modal');
};

function updateVerificationFormFields() {
    const methodElem = document.getElementById('alarm-verification-method');
    if (!methodElem) return;
    const method = methodElem.value;
    const stepsGroup = document.getElementById('verif-steps-group');
    const consecutiveGroup = document.getElementById('verif-consecutive-group');
    const accuracyGroup = document.getElementById('verif-accuracy-group');
    const timeGroup = document.getElementById('verif-time-group');

    if (stepsGroup) stepsGroup.style.display = (method === 'multi_step' || method === 'accuracy_check') ? 'block' : 'none';
    if (consecutiveGroup) consecutiveGroup.style.display = (method === 'consecutive_correct') ? 'block' : 'none';
    if (accuracyGroup) accuracyGroup.style.display = (method === 'accuracy_check') ? 'block' : 'none';
    if (timeGroup) timeGroup.style.display = 'block';
}

document.getElementById('alarm-verification-method')?.addEventListener('change', updateVerificationFormFields);

// Format time 24H -> 12H
function formatTime12(timeString) {
    const [hoursStr, minutesStr] = timeString.split(':');
    const hours = parseInt(hoursStr);
    const ampm = hours >= 12 ? 'PM' : 'AM';
    const displayHours = hours % 12 || 12;
    return `${displayHours}:${minutesStr} ${ampm}`;
}



const clientFallbackChallenges = [
    {
        type: 'Math Problems',
        difficulty: 'Medium',
        question: 'What is 14 x 6 + 18?',
        options: ['98', '102', '106', '112'],
        answer: '102',
        explanation: '14 x 6 = 84; 84 + 18 = 102.'
    },
    {
        type: 'Logic Puzzles',
        difficulty: 'Medium',
        question: 'If ALL roses are flowers and SOME flowers fade quickly, which is guaranteed?',
        options: ['All roses fade quickly', 'Some flowers are roses', 'No roses fade', 'All flowers are roses'],
        answer: 'Some flowers are roses',
        explanation: 'Because all roses are flowers, some flowers must be roses.'
    },
    {
        type: 'Pattern Recognition',
        difficulty: 'Medium',
        question: 'Complete the pattern: 3, 7, 15, 31, ?',
        options: ['47', '55', '63', '71'],
        answer: '63',
        explanation: 'Each term is (previous x 2) + 1. 31 x 2 + 1 = 63.'
    },
    {
        type: 'Word Games',
        difficulty: 'Medium',
        question: 'Unscramble the morning word: "W A K E U P"',
        options: ['WAKEUP', 'PAUKWE', 'WEAKUP', 'POWAKE'],
        answer: 'WAKEUP',
        explanation: 'The unscrambled word is WAKEUP.'
    }
];

// 7. Dynamic Cognitive Challenge Drill & Verification
window.triggerChallenge = (method = 'multi_step', steps = 3, challengeType = 'Math Problems', diff = 'Medium') => {
    const timeLimit = method === 'time_based' ? 15 : 20;
    const reqAcc = method === 'accuracy_check' ? 67 : (method === 'multi_step' ? 67 : 100);
    const consecReq = method === 'consecutive_correct' ? 2 : 1;
    const totalSteps = method === 'multi_step' || method === 'accuracy_check' ? Math.max(2, steps || 3) : (method === 'consecutive_correct' ? 2 : 1);

    fetch(`${window.API_BASE_URL}/api/challenges/verification/start`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
            verification_method: method || 'multi_step',
            verification_steps: totalSteps,
            required_accuracy: reqAcc,
            consecutive_required: consecReq,
            time_limit: timeLimit,
            challenge_type: challengeType || 'Math Problems',
            difficulty: diff || 'Medium'
        })
    })
    .then(res => res.json())
    .then(data => {
        currentVerificationState = {
            sessionId: data.session_id,
            status: data.status || 'in_progress',
            method: data.verification_method || method || 'multi_step',
            currentStep: data.current_step || 1,
            totalSteps: data.total_steps || totalSteps,
            correctCount: data.correct_count || 0,
            requiredAccuracy: data.required_accuracy || reqAcc,
            consecutiveCorrect: data.consecutive_correct || 0,
            consecutiveRequired: data.consecutive_required || consecReq,
            timeLimit: data.time_limit || timeLimit,
            timeRemaining: data.time_limit || timeLimit
        };
        renderVerificationHUD(currentVerificationState);
        displayCognitiveChallenge(data.current_challenge, 1);
    })
    .catch(err => {
        console.warn('Backend verification session unavailable, running client-side multi-step drill:', err);
        currentVerificationState = {
            sessionId: 'client_drill_' + Date.now(),
            status: 'in_progress',
            method: method || 'multi_step',
            currentStep: 1,
            totalSteps: totalSteps,
            correctCount: 0,
            requiredAccuracy: reqAcc,
            consecutiveCorrect: 0,
            consecutiveRequired: consecReq,
            timeLimit: timeLimit,
            timeRemaining: timeLimit
        };
        renderVerificationHUD(currentVerificationState);
        displayCognitiveChallenge(clientFallbackChallenges[0], 1);
    });
};

window.triggerMathChallenge = () => {
    window.triggerChallenge('multi_step', 3, 'Math Problems', 'Easy');
};

// Handle checking answer via backend API and verification step engine
const submitChallengeBtn = document.getElementById('submit-challenge-btn');
if (submitChallengeBtn) {
    submitChallengeBtn.addEventListener('click', async () => {
        if (verificationRequestInFlight) return;
        let userAnswer = '';
        if (activeCognitiveChallenge && activeCognitiveChallenge.options && activeCognitiveChallenge.options.length > 0) {
            userAnswer = selectedChallengeOption || '';
        } else {
            const inputElem = document.getElementById('challenge-answer');
            userAnswer = inputElem ? inputElem.value.trim() : '';
        }

        const feedback = document.getElementById('challenge-feedback');

        if (!userAnswer) {
            if (feedback) {
                feedback.style.color = 'var(--color-danger)';
                feedback.textContent = 'Please select or enter an answer first!';
            }
            return;
        }

        const timeTaken = Math.round((Date.now() - challengeStartTime) / 1000);
        stopChallengeTimer();
        verificationRequestInFlight = true;

        try {
            const response = await fetch(`${window.API_BASE_URL}/api/challenges/verification/step`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    session_id: currentVerificationState.sessionId || (activeCognitiveChallenge ? activeCognitiveChallenge.id : ''),
                    step_number: currentVerificationState.currentStep,
                    challenge_id: activeCognitiveChallenge ? activeCognitiveChallenge.id : null,
                    user_answer: userAnswer,
                    time_taken: timeTaken,
                    is_timeout: false,
                    alarm_id: currentRingingAlarm ? currentRingingAlarm.id : null
                })
            });

            if (response.ok) {
                const resData = await response.json();
                currentVerificationState.status = resData.verification_status;
                currentVerificationState.currentStep = resData.current_step;
                currentVerificationState.totalSteps = resData.total_steps;
                currentVerificationState.correctCount = resData.correct_count;
                currentVerificationState.consecutiveCorrect = resData.consecutive_correct;
                currentVerificationState.consecutiveRequired = resData.consecutive_required;
                renderVerificationHUD(currentVerificationState);

                if (resData.verification_status === 'passed') {
                    // Verification passed; rating and the alarm action are still required.
                    window.isWakeUpVerified = false;
                    feedback.style.color = 'var(--color-success)';
                    feedback.textContent = resData.message || 'Wake-up verified. Rate your wakefulness.';
                    showWakefulnessScreen();
                } else if (resData.verification_status === 'in_progress') {
                    currentAttemptNumber++;
                    feedback.style.color = resData.is_step_correct ? 'var(--color-success)' : 'var(--color-warning)';
                    feedback.textContent = resData.message;

                    if (resData.next_challenge) {
                        setTimeout(() => {
                            displayCognitiveChallenge(resData.next_challenge, currentAttemptNumber);
                        }, 400);
                    } else {
                        startChallengeTimer(currentVerificationState.timeLimit || 20);
                    }
                } else {
                    currentAttemptNumber++;
                    const modalContainer = document.querySelector('#challenge-modal .modal-container');
                    if (modalContainer) {
                        modalContainer.classList.add('challenge-shake');
                        setTimeout(() => modalContainer.classList.remove('challenge-shake'), 600);
                    }

                    feedback.style.color = 'var(--color-danger)';
                    feedback.textContent = resData.message || '✗ Incorrect answer. Streak reset! Try again:';

                    if (resData.next_challenge) {
                        setTimeout(() => {
                            displayCognitiveChallenge(resData.next_challenge, currentAttemptNumber);
                        }, 500);
                    } else {
                        startChallengeTimer(currentVerificationState.timeLimit || 20);
                    }
                }
            } else {
                throw new Error('Server response error');
            }
        } catch (e) {
            console.warn('Advancing verification step in client mode:', e);
            // Client-side multi-step fallback progression
            const isCorrect = (activeCognitiveChallenge && activeCognitiveChallenge.answer && 
                userAnswer.trim().toLowerCase() === activeCognitiveChallenge.answer.trim().toLowerCase());

            if (isCorrect) {
                currentVerificationState.correctCount = (currentVerificationState.correctCount || 0) + 1;
                currentVerificationState.consecutiveCorrect = (currentVerificationState.consecutiveCorrect || 0) + 1;
            } else {
                currentVerificationState.consecutiveCorrect = 0;
            }

            if (currentVerificationState.currentStep < currentVerificationState.totalSteps) {
                currentVerificationState.currentStep += 1;
                currentVerificationState.status = 'in_progress';
                renderVerificationHUD(currentVerificationState);

                feedback.style.color = isCorrect ? 'var(--color-success)' : 'var(--color-warning)';
                feedback.textContent = `${isCorrect ? '✓ Correct!' : '✗ Incorrect.'} Moving to Question ${currentVerificationState.currentStep}/${currentVerificationState.totalSteps}:`;

                const nextChalIndex = (currentVerificationState.currentStep - 1) % clientFallbackChallenges.length;
                setTimeout(() => {
                    displayCognitiveChallenge(clientFallbackChallenges[nextChalIndex], currentAttemptNumber + 1);
                }, 400);
            } else {
                // Final Step Reached
                const acc = Math.round((currentVerificationState.correctCount / currentVerificationState.totalSteps) * 100);
                const passed = acc >= (currentVerificationState.requiredAccuracy || 67);

                if (passed) {
                    window.isWakeUpVerified = true;
                    currentVerificationState.status = 'passed';
                    renderVerificationHUD(currentVerificationState);

                    feedback.style.color = 'var(--color-success)';
                    feedback.textContent = `✓ Multi-Step Wake-Up Verified! (${currentVerificationState.correctCount}/${currentVerificationState.totalSteps} correct)`;

                    stopAlarmSound();
                    stopChallengeTimer();
                    Toast.show('Wake-Up Verified!', 'Neural activation complete! +10 Points.', 'success', 3000);

                    setTimeout(() => {
                        Modal.close('challenge-modal');
                    }, 1400);
                } else {
                    currentVerificationState.totalSteps += 1;
                    currentVerificationState.currentStep += 1;
                    currentVerificationState.status = 'failed';
                    renderVerificationHUD(currentVerificationState);

                    feedback.style.color = 'var(--color-danger)';
                    feedback.textContent = `✗ Accuracy ${acc}% below required. Additional question required:`;
                    const nextChalIndex = (currentVerificationState.currentStep - 1) % clientFallbackChallenges.length;
                    setTimeout(() => {
                        displayCognitiveChallenge(clientFallbackChallenges[nextChalIndex], currentAttemptNumber + 1);
                    }, 500);
                }
            }
        } finally {
            verificationRequestInFlight = false;
        }
    });
}

function renderHistoryLog() {
    const tableBody = document.querySelector('#tab-dashboard table:nth-of-type(2) tbody') ||
        document.querySelector('table tbody'); // Fallback lookup
    if (tableBody) {
        // Find challenge history table body specifically
        const tables = document.querySelectorAll('table');
        tables.forEach(table => {
            const header = table.querySelector('th');
            if (header && header.textContent.includes('CHALLENGE')) {
                const tbody = table.querySelector('tbody');
                tbody.innerHTML = '';
                challengeHistory.slice(0, 3).forEach(c => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><i class="fas fa-calculator text-muted" style="margin-right:8px;"></i> ${c.mode}</td>
                        <td><span class="badge badge-success">${c.score}</span></td>
                        <td>${c.date}</td>
                    `;
                    tbody.appendChild(tr);
                });
            }
        });
    }
}

// 8. Notifications Manager (Real PostgreSQL Notifications)
async function renderNotifications() {
    const list = document.getElementById('full-notifications-list');
    if (!list) return;

    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/?limit=20`, {
            headers: getAuthHeaders()
        });
        if (resp.ok) {
            const data = await resp.json();
            const realNotifs = data.notifications || [];
            list.innerHTML = '';
            if (realNotifs.length === 0) {
                list.innerHTML = '<p style="color:var(--text-secondary); text-align:center; padding:20px;">No active alerts.</p>';
                return;
            }

            realNotifs.forEach(n => {
                const item = document.createElement('div');
                item.className = `notification-item ${n.is_read ? 'read' : 'unread'}`;
                const iconClass = n.type === 'alarm' ? 'fa-bell' : (n.type === 'challenge' ? 'fa-puzzle-piece' : (n.type === 'progress' ? 'fa-chart-line' : 'fa-info-circle'));
                const colorClass = n.type === 'alarm' ? 'yellow' : (n.type === 'challenge' ? 'purple' : 'blue');
                item.innerHTML = `
                    <div class="notification-item-icon ${colorClass}"><i class="fas ${iconClass}"></i></div>
                    <div class="notification-text">
                        <h4>${n.title}</h4>
                        <p>${n.message}</p>
                        <span>${n.time_ago || (n.created_at ? new Date(n.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : 'Recently')}</span>
                    </div>
                `;
                list.appendChild(item);
            });
            return;
        }
    } catch (e) {
        console.debug('Error fetching user notifications:', e);
    }

    list.innerHTML = '<p style="color:var(--text-secondary); text-align:center; padding:20px;">No new alerts.</p>';
}

window.clearNotifications = async () => {
    try {
        await fetch(`${window.API_BASE_URL}/api/notifications/mark-all-read`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
    } catch (_) {}
    renderNotifications();
    if (typeof Toast !== 'undefined') {
        Toast.show('Notifications Cleared', 'All alerts marked as read.', 'info', 2000);
    }
};

// 9. Add Alarm Form Submission
const addAlarmForm = document.getElementById('add-alarm-form');
if (addAlarmForm) {
    // Intercept clicks to "Add Alarm" button to reset form to creation mode
    document.querySelectorAll('[onclick="Modal.open(\'add-alarm-modal\')"]').forEach(btn => {
        btn.removeAttribute('onclick');
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('edit-alarm-id').value = '';
            addAlarmForm.reset();
            const alarmTypeSelect = document.getElementById('alarm-type');
            if (alarmTypeSelect) {
                alarmTypeSelect.value = 'One-Time';
            }
            const verifMethodSelect = document.getElementById('alarm-verification-method');
            if (verifMethodSelect) {
                verifMethodSelect.value = 'multi_step';
            }
            const verifStepsSelect = document.getElementById('alarm-verif-steps');
            if (verifStepsSelect) {
                verifStepsSelect.value = '3';
            }
            updateCustomDaysVisibility();
            updateVerificationFormFields();
            const modalTitle = document.getElementById('alarm-modal-title');
            if (modalTitle) modalTitle.textContent = 'Set Cognitive Alarm';
            Modal.open('add-alarm-modal');
        });
    });

    document.getElementById('alarm-type')?.addEventListener('change', updateCustomDaysVisibility);
    document.getElementById('alarm-verification-method')?.addEventListener('change', updateVerificationFormFields);

    function getInputValue(idCandidates, fallback = '') {
        for (const id of idCandidates) {
            const elem = document.getElementById(id);
            if (elem && elem.value !== undefined && elem.value !== null && elem.value !== '') {
                return elem.value;
            }
        }
        return fallback;
    }

    addAlarmForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const alarmId = getInputValue(['edit-alarm-id'], '');
        const rawTitle = getInputValue(['alarm-label', 'alarm-title-input'], 'Wakeup Alarm');
        const title = rawTitle.trim() || 'Wakeup Alarm';
        const alarm_time = getInputValue(['alarm-time', 'alarm-time-input'], '07:00');
        const alarm_type = getInputValue(['alarm-type', 'alarm-repeat-select'], 'Daily');
        const challenge = getInputValue(['alarm-challenge', 'alarm-challenge-select'], 'Math Problems');
        const difficulty_level = getInputValue(['alarm-difficulty'], 'Medium');
        const sound = getInputValue(['alarm-sound'], 'Radar');
        const vibration = getInputValue(['alarm-vibration'], 'Standard');
        const snooze_duration = parseInt(getInputValue(['alarm-snooze-duration'], '5')) || 5;
        const max_snoozes = parseInt(getInputValue(['alarm-max-snoozes'], '3')) || 0;

        const verification_method = getInputValue(['alarm-verification-method'], 'multi_step');
        const verification_steps = parseInt(getInputValue(['alarm-verif-steps'], '3')) || 3;
        const consecutive_required = parseInt(getInputValue(['alarm-verif-consecutive'], '2')) || 2;
        const required_accuracy = parseFloat(getInputValue(['alarm-verif-accuracy'], '67')) || 67.0;
        const time_limit = parseInt(getInputValue(['alarm-verif-time'], '20')) || 20;

        const checkedDays = [];
        addAlarmForm.querySelectorAll('#custom-days-container input[type="checkbox"]:checked').forEach(cb => {
            checkedDays.push(cb.value);
        });

        let repeat_days = '';
        switch (alarm_type) {
            case 'One-Time':
                repeat_days = '';
                break;
            case 'Daily':
                repeat_days = 'Mon,Tue,Wed,Thu,Fri,Sat,Sun';
                break;
            case 'Weekdays':
                repeat_days = 'Mon,Tue,Wed,Thu,Fri';
                break;
            case 'Weekends':
                repeat_days = 'Sat,Sun';
                break;
            case 'Custom':
                repeat_days = checkedDays.join(',');
                if (!repeat_days) {
                    Toast.show('Error', 'Please select at least one repeating day for a custom alarm.', 'danger', 2500);
                    return;
                }
                break;
            case 'Weekday':
                repeat_days = 'Mon,Tue,Wed,Thu,Fri';
                break;
            case 'Weekend':
                repeat_days = 'Sat,Sun';
                break;
            default:
                repeat_days = '';
        }

        const payload = {
            title,
            alarm_time,
            alarm_type,
            repeat_days,
            is_active: true,
            challenge,
            difficulty_level,
            sound,
            vibration,
            snooze_duration,
            max_snoozes,
            verification_method,
            verification_steps,
            required_accuracy,
            consecutive_required,
            time_limit
        };

        try {
            let response;
            if (alarmId) {
                response = await fetch(`${window.API_BASE_URL}/api/alarms/${alarmId}`, {
                    method: 'PUT',
                    headers: getAuthHeaders(),
                    body: JSON.stringify(payload)
                });
            } else {
                response = await fetch(`${window.API_BASE_URL}/api/alarms/`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify(payload)
                });
            }

            if (response.ok) {
                const savedAlarm = await response.json();
                if (alarmId) {
                    const idx = alarms.findIndex(a => a.id === parseInt(alarmId));
                    if (idx !== -1) alarms[idx] = savedAlarm;
                    Toast.show('Alarm Updated', `"${title}" was saved successfully.`, 'success', 3000);
                } else {
                    alarms.push(savedAlarm);
                    Toast.show('Alarm Created', `"${title}" alarm set for ${formatTime12(alarm_time)}`, 'success', 3000);
                }

                renderAlarms();
                Modal.close('add-alarm-modal');
                addAlarmForm.reset();
                document.getElementById('edit-alarm-id').value = '';
            } else {
                const errData = await response.json().catch(() => ({}));
                const errMsg = errData.detail ? (Array.isArray(errData.detail) ? errData.detail.map(e => e.msg).join(', ') : errData.detail) : 'Failed to save alarm.';
                Toast.show('Error', errMsg, 'danger', 3000);
            }
        } catch (e) {
            console.error('Error saving alarm:', e);
            Toast.show('Error', 'Network error. Check backend connection.', 'danger', 3000);
        }
    });
}

// 10. Profile Settings Form
const profileForm = document.getElementById('profile-settings-form');
async function loadUserProfileSettings() {
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el && val !== undefined && val !== null) el.value = val;
    };

    // 1. Instant local session population so inputs are never blank
    const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
    if (session.name) setVal('profile-name', session.name);
    if (session.email) setVal('profile-email', session.email);
    if (session.phone_number) setVal('profile-phone', session.phone_number);
    if (session.target_bedtime) setVal('profile-bedtime-target', session.target_bedtime);
    if (session.target_wake_time) setVal('profile-wake-target', session.target_wake_time);
    if (session.inactivity_threshold_minutes) setVal('profile-inactivity-threshold', session.inactivity_threshold_minutes);

    if (typeof updateHeaderUserInfo === 'function') updateHeaderUserInfo();

    // 2. Fetch latest verified profile from API
    try {
        const headers = getAuthHeaders();
        const response = await fetch(`${window.API_BASE_URL}/api/auth/me`, { headers });
        if (response.ok) {
            const user = await response.json();
            if (user.name) setVal('profile-name', user.name);
            if (user.email) setVal('profile-email', user.email);
            if (user.phone_number) setVal('profile-phone', user.phone_number);
            if (user.target_bedtime) setVal('profile-bedtime-target', user.target_bedtime);
            if (user.target_wake_time) setVal('profile-wake-target', user.target_wake_time);
            if (user.inactivity_threshold_minutes) setVal('profile-inactivity-threshold', user.inactivity_threshold_minutes);

            // Synchronize active session in localStorage
            session.name = user.name || session.name;
            session.email = user.email || session.email;
            session.phone_number = user.phone_number;
            session.target_bedtime = user.target_bedtime;
            session.target_wake_time = user.target_wake_time;
            session.inactivity_threshold_minutes = user.inactivity_threshold_minutes;
            localStorage.setItem('sessionUser', JSON.stringify(session));

            if (typeof updateHeaderUserInfo === 'function') updateHeaderUserInfo();
        }
    } catch (e) {
        console.warn('Could not load user profile from API, fallback used:', e);
    }
}
loadUserProfileSettings();

if (profileForm) {
    profileForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const nameVal = document.getElementById('profile-name')?.value;
        const emailVal = document.getElementById('profile-email')?.value;
        const phoneVal = document.getElementById('profile-phone')?.value;
        const bedtimeVal = document.getElementById('profile-bedtime-target')?.value;
        const wakeVal = document.getElementById('profile-wake-target')?.value;
        const thresholdVal = parseInt(document.getElementById('profile-inactivity-threshold')?.value) || 30;

        try {
            const headers = getAuthHeaders();
            const res = await fetch(`${window.API_BASE_URL}/api/auth/profile`, {
                method: 'PUT',
                headers,
                body: JSON.stringify({
                    name: nameVal,
                    email: emailVal,
                    phone_number: phoneVal,
                    target_bedtime: bedtimeVal,
                    target_wake_time: wakeVal,
                    inactivity_threshold_minutes: thresholdVal
                })
            });
            if (res.ok) {
                const updated = await res.json();
                const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
                session.name = updated.name;
                session.email = updated.email;
                session.phone_number = updated.phone_number;
                session.target_bedtime = updated.target_bedtime;
                session.target_wake_time = updated.target_wake_time;
                session.inactivity_threshold_minutes = updated.inactivity_threshold_minutes;
                localStorage.setItem('sessionUser', JSON.stringify(session));

                if (typeof updateHeaderUserInfo === 'function') updateHeaderUserInfo();
                Toast.show('Profile Settings Saved', 'Your profile, phone number, and sleep schedule were updated successfully.', 'success', 2500);

                // Refresh habit score and sleep adherence immediately
                if (typeof fetchHabitScoreData === 'function') {
                    fetchHabitScoreData(typeof currentHabitPeriod !== 'undefined' ? currentHabitPeriod : '7days');
                }
            } else {
                const errData = await res.json().catch(() => ({}));
                Toast.show('Update Failed', errData.detail || 'Could not update profile.', 'danger', 3000);
            }
        } catch (err) {
            console.error('Error saving profile settings:', err);
            Toast.show('Network Error', 'Could not save profile settings to server.', 'warning', 2500);
        }
    });
}

// 11. PDF/Text report builder download
window.simulateReportDownload = () => {
    const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
    const userName = session.name || (session.email ? session.email.split('@')[0] : 'User');
    Toast.show('Preparing Report...', 'Assembling sleep log and cognitive matrix scores.', 'info', 2000);
    setTimeout(() => {
        const text = `WAKEWISE AI - SLEEP PERFORMANCE REPORT
--------------------------------------
REPORT FOR: ${userName}
DATE GENERATED: ${new Date().toLocaleDateString()}
SLEEP CONSISTENCY RATIO: 94%
AVERAGE COGNITIVE ACCURACY: 92%
WAKE STREAK ACHIEVED: 14 Days
--------------------------------------
RECOMMENDATIONS:
"Great sleep pattern adherence. Keep maintaining consistent wake schedules!"
--------------------------------------
Report generated dynamically by WakeWise AI Platform.`;

        const blob = new Blob([text], { type: 'text/plain' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `WakeWiseAI-${userName.replace(/\s+/g, '_')}-Report.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

        Toast.show('Report Downloaded', 'The text sleep analysis file was saved.', 'success', 2500);
    }, 1500);
};

// 12. Run setup on load
document.addEventListener('DOMContentLoaded', () => {
    if (typeof updateHeaderUserInfo === 'function') updateHeaderUserInfo();
    fetchAlarmsFromServer();
    fetchAnalyticsData();
    fetchHabitScoreData();
    fetchBehavioralAnalyticsData();
    renderHistoryLog();
    renderNotifications();
});

// (Duplicate checkTriggeredAlarm removed; unified in startAlarmMonitor)

// ==========================================================================
// REAL PERFORMANCE & ANALYTICS DATA CONTROLLER
// ==========================================================================
let analyticsChartInstance = null;
let dbAnalyticsChartInstance = null;

let currentHabitPeriod = 7;

window.setHabitPeriod = function(periodDays) {
    currentHabitPeriod = periodDays;
    [1, 7, 30].forEach(p => {
        const btn = document.getElementById(`habit-period-${p}`);
        if (btn) {
            btn.className = (p === periodDays) ? 'btn btn-primary' : 'btn btn-secondary';
        }
    });
    fetchHabitScoreData(periodDays);
};

// Activity Heartbeat debounced tracker (Requirement 14 & 5B)
let lastActivityHeartbeat = 0;
function reportUserActivityHeartbeat() {
    const now = Date.now();
    if (now - lastActivityHeartbeat < 60000) return; // Debounce to at most once per minute
    lastActivityHeartbeat = now;
    const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
    if (!session.accessToken) return;

    fetch(`${window.API_BASE_URL}/api/analytics/activity`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ timestamp: new Date().toISOString() })
    }).catch(e => console.debug('Activity heartbeat ping note:', e));
}

// Attach activity listeners for phone/browser interaction
['click', 'keydown', 'touchstart', 'scroll'].forEach(evt => {
    window.addEventListener(evt, reportUserActivityHeartbeat, { passive: true });
});

async function fetchHabitScoreData(periodDays = 7) {
    try {
        const headers = getAuthHeaders();
        const [scoreRes, weeklyRes, sleepRes] = await Promise.all([
            fetch(`${window.API_BASE_URL}/api/analytics/habit-score?period_days=${periodDays}`, { headers }),
            fetch(`${window.API_BASE_URL}/api/analytics/habit-score/weekly`, { headers }),
            fetch(`${window.API_BASE_URL}/api/analytics/sleep-adherence`, { headers })
        ]);

        const setText = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value;
        };

        const setProgress = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.style.width = `${Math.max(0, Math.min(100, Number(value) || 0))}%`;
        };

        if (scoreRes.ok) {
            const data = await scoreRes.json();
            const breakdown = data.breakdown || {};
            const level = data.level || 'Poor';
            const score = Number(data.habit_score || 0);

            setText('stat-habit-score', score.toFixed(0));
            setText('habit-score-value', score.toFixed(0));
            setText('habit-score-level', level);
            setText('habit-wake-score', `${Number(breakdown.wake_up_consistency || 0).toFixed(0)}/100`);
            setText('habit-challenge-score', `${Number(breakdown.challenge_completion || 0).toFixed(0)}/100`);
            setText('habit-snooze-score', `${Number(breakdown.snooze_reduction || 0).toFixed(0)}/100`);
            setText('habit-sleep-score', `${Number(breakdown.sleep_schedule_adherence || 0).toFixed(0)}/100`);

            setProgress('habit-wake-bar', breakdown.wake_up_consistency || 0);
            setProgress('habit-challenge-bar', breakdown.challenge_completion || 0);
            setProgress('habit-snooze-bar', breakdown.snooze_reduction || 0);
            setProgress('habit-sleep-bar', breakdown.sleep_schedule_adherence || 0);

            const listEl = document.getElementById('habit-insights-list');
            if (listEl) {
                const insights = Array.isArray(data.insights) && data.insights.length ? data.insights : ['Start completing challenges and tracking routine to generate habit insights.'];
                listEl.innerHTML = insights.map(item => `<li>${item}</li>`).join('');
            }

            const badge = document.getElementById('habit-score-level');
            if (badge) {
                badge.className = 'badge';
                const mapping = {
                    'Excellent': 'badge-success',
                    'Good': 'badge-success',
                    'Fair': 'badge-warning',
                    'Needs Improvement': 'badge-warning',
                    'Poor': 'badge-danger'
                };
                badge.classList.add(mapping[level] || 'badge-secondary');
            }
        }

        // Weekly comparison & deltas
        if (weeklyRes.ok) {
            const history = await weeklyRes.json();
            const thisWk = history.this_week ?? history.weekly_scores?.['This Week'] ?? '--';
            const lastWk = history.last_week ?? history.weekly_scores?.['Last Week'] ?? '--';
            const changeVal = history.change ?? history.weekly_scores?.['Change'] ?? 0;
            const changes = history.score_changes || {};

            setText('habit-history-this-week', typeof thisWk === 'number' ? thisWk.toFixed(0) : thisWk);
            setText('habit-history-last-week', typeof lastWk === 'number' ? lastWk.toFixed(0) : lastWk);

            const changeEl = document.getElementById('habit-history-change');
            if (changeEl) {
                const formatted = changeVal > 0 ? `+${changeVal.toFixed(0)}` : `${changeVal.toFixed(0)}`;
                changeEl.textContent = formatted;
                changeEl.style.color = changeVal >= 0 ? '#22c55e' : '#ef4444';
            }

            const wakeDelta = changes.wake_up_consistency ?? 0;
            const chalDelta = changes.challenge_completion ?? 0;
            setText('habit-delta-wake', wakeDelta >= 0 ? `+${wakeDelta.toFixed(0)}` : `${wakeDelta.toFixed(0)}`);
            setText('habit-delta-challenge', chalDelta >= 0 ? `+${chalDelta.toFixed(0)}` : `${chalDelta.toFixed(0)}`);
        }

        // Sleep Routine Details & Phone Inactivity Estimation
        if (sleepRes.ok) {
            const sleep = await sleepRes.json();
            setText('sleep-target-bedtime', sleep.target_bedtime || '--:--');
            setText('sleep-estimated-time', sleep.estimated_sleep_time || 'Pending...');
            setText('sleep-target-wake', sleep.target_wake_time || '--:--');
            setText('sleep-actual-wake', sleep.actual_wake_time || '--:--');

            const insightText = sleep.insight || sleep.summary || 'Sleep Schedule Adherence: Insufficient Data';
            setText('sleep-adherence-insight-text', insightText);

            const badge = document.getElementById('habit-sleep-estimate-badge');
            if (badge) {
                if (sleep.estimated_from_phone_inactivity) {
                    badge.textContent = 'Estimated from phone inactivity';
                    badge.style.display = 'inline-block';
                } else if (sleep.status === 'partial') {
                    badge.textContent = 'Wake-time adherence only';
                    badge.style.display = 'inline-block';
                } else {
                    badge.textContent = 'Awaiting inactivity data';
                    badge.style.display = 'inline-block';
                }
            }
        }
    } catch (e) {
        console.error('Error fetching habit score data:', e);
    }
}

async function fetchBehavioralAnalyticsData() {
    try {
        const headers = getAuthHeaders();
        const response = await fetch(`${window.API_BASE_URL}/api/analytics/behavioral`, { headers });
        if (!response.ok) {
            const msg = 'Insufficient data';
            const ids = ['behavior-consistency', 'behavior-snoozes', 'behavior-wakefulness', 'behavior-wake-time', 'behavior-streak', 'db-behavior-consistency', 'db-behavior-snoozes', 'db-behavior-wakefulness', 'db-behavior-wake-time', 'db-behavior-streak'];
            ids.forEach(id => { const el = document.getElementById(id); if (el) el.textContent = msg; });
            ['behavior-patterns-list', 'behavior-insights-list', 'db-behavior-patterns-list', 'db-behavior-insights-list'].forEach(id => {
                const el = document.getElementById(id); if (el) el.innerHTML = '<li>Insufficient data.</li>';
            });
            return;
        }

        const data = await response.json();
        const snoozePattern = data.snooze_pattern || {};
        const habit = data.habit_consistency || {};
        const wakeUp = data.wake_up_behavior || {};
        const insights = data.insights || [];

        const labels = [
            ['behavior-consistency', 'db-behavior-consistency'],
            ['behavior-snoozes', 'db-behavior-snoozes'],
            ['behavior-wakefulness', 'db-behavior-wakefulness'],
            ['behavior-wake-time', 'db-behavior-wake-time'],
            ['behavior-streak', 'db-behavior-streak']
        ];

        const consistency = Number(habit.wake_up_consistency_percentage || 0);
        const avgSnoozes = Number(snoozePattern.average_snoozes_per_alarm || 0);
        const avgWakefulness = Number(wakeUp.average_wakefulness_rating || 0);
        const avgWakeTime = habit.average_wake_up_time || '--:--';
        const streak = Number(habit.wake_up_streak || 0);

        const setText = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
        setText('behavior-consistency', `${consistency.toFixed(0)}%`);
        setText('behavior-snoozes', avgSnoozes.toFixed(1));
        setText('behavior-wakefulness', `${avgWakefulness.toFixed(1)}/5`);
        setText('behavior-wake-time', avgWakeTime);
        setText('behavior-streak', `${streak} day${streak === 1 ? '' : 's'}`);

        ['db-behavior-consistency', 'db-behavior-snoozes', 'db-behavior-wakefulness', 'db-behavior-wake-time', 'db-behavior-streak'].forEach((id, index) => {
            const target = labels[index];
            if (target && target[1] === id) {
                const val = [
                    `${consistency.toFixed(0)}%`,
                    avgSnoozes.toFixed(1),
                    `${avgWakefulness.toFixed(1)}/5`,
                    avgWakeTime,
                    `${streak} day${streak === 1 ? '' : 's'}`
                ][index];
                setText(id, val);
            }
        });

        const patterns = [
            `Total snoozes: ${snoozePattern.total_snoozes ?? 0}`,
            `Most snoozed day: ${snoozePattern.most_frequently_snoozed_days?.[0] || 'Insufficient data'}`,
            `Successful verification days: ${habit.successful_wake_up_days ?? 0}`,
            `Failed/missed days: ${habit.missed_or_failed_verification_days ?? 0}`
        ];

        const listRenderer = (listId, items) => {
            const el = document.getElementById(listId);
            if (!el) return;
            el.innerHTML = items.length ? items.map(item => `<li>${item}</li>`).join('') : '<li>Insufficient data.</li>';
        };

        listRenderer('behavior-patterns-list', patterns);
        listRenderer('db-behavior-patterns-list', patterns);
        listRenderer('behavior-insights-list', insights.length ? insights : ['Insufficient data to generate a behavioral trend insight yet.']);
        listRenderer('db-behavior-insights-list', insights.length ? insights : ['Insufficient data to generate a behavioral trend insight yet.']);
    } catch (e) {
        console.error('Error fetching behavioral analytics:', e);
    }
}

async function fetchAnalyticsData() {
    try {
        const headers = getAuthHeaders();

        // 1. Summary Metrics
        const summaryRes = await fetch(`${window.API_BASE_URL}/api/analytics/summary`, { headers });
        let strongTypes = [];
        let weakTypes = [];

        if (summaryRes.ok) {
            const summary = await summaryRes.json();
            strongTypes = summary.strong_types || [];
            weakTypes = summary.weak_types || [];

            const accStr = `${summary.overall_accuracy}%`;
            const passedStr = summary.passed_challenges;
            const failedStr = summary.failed_challenges;
            const timeStr = `${summary.average_completion_time}s`;
            const streakStr = `${summary.current_streak} Days 🔥`;
            const diffStr = `Recommended: ${summary.recommended_difficulty}`;
            const cognitiveScore = summary.cognitive_score != null ? Math.round(summary.cognitive_score) : 50;
            const rawTrend = (summary.trend || 'stable').toLowerCase();
            const trendLabel = rawTrend === 'improving' ? 'Improving 🚀' : (rawTrend === 'declining' ? 'Declining 📉' : 'Stable ⚖️');
            const reasonText = summary.recommendation_reason || 'Calibrating personalized challenge difficulty.';

            ['analytics-accuracy', 'db-analytics-accuracy'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = accStr;
            });

            ['analytics-passed', 'db-analytics-passed'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = passedStr;
            });

            ['analytics-failed', 'db-analytics-failed'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = failedStr;
            });

            ['analytics-avg-time', 'db-analytics-avg-time'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = timeStr;
            });

            ['analytics-streak', 'db-analytics-streak'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = streakStr;
            });

            ['recommended-diff-badge', 'db-recommended-diff-badge'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = diffStr;
            });

            // Populate Cognitive Score & Trend
            ['cognitive-score-val', 'db-cognitive-score-val'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = cognitiveScore;
            });

            ['performance-trend-val', 'db-performance-trend-val'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = trendLabel;
            });

            // Populate Adaptive Recommendation Reason
            ['adaptive-reason-text', 'db-adaptive-reason-text'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = reasonText;
            });

            // Populate Strong Types List
            const strongHtml = strongTypes.length > 0
                ? strongTypes.map(t => `<span style="background: rgba(34, 197, 94, 0.18); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4); padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; display: inline-flex; align-items: center; gap: 6px;"><i class="fas fa-check-circle"></i> ${t}</span>`).join('')
                : '<span style="color: var(--text-muted); font-size: 0.82rem;">Complete more sessions with &ge;85% accuracy to unlock domain mastery.</span>';

            ['strong-types-list', 'db-strong-types-list'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = strongHtml;
            });

            // Populate Weak Types List
            const weakHtml = weakTypes.length > 0
                ? weakTypes.map(t => `<span style="background: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; display: inline-flex; align-items: center; gap: 6px;"><i class="fas fa-exclamation-triangle"></i> ${t}</span>`).join('')
                : '<span style="color: #4ade80; font-size: 0.82rem;"><i class="fas fa-shield-alt"></i> No weak challenge domains detected (&ge;70% across domains).</span>';

            ['weak-types-list', 'db-weak-types-list'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = weakHtml;
            });
        }

        // 2. Performance by Type (with strong/weak domain badges)
        const byTypeRes = await fetch(`${window.API_BASE_URL}/api/analytics/by-type`, { headers });
        if (byTypeRes.ok) {
            const typeData = await byTypeRes.json();
            renderAnalyticsBreakdown('by-type', typeData, strongTypes, weakTypes);
        }

        // 3. Performance by Difficulty
        const byDiffRes = await fetch(`${window.API_BASE_URL}/api/analytics/by-difficulty`, { headers });
        if (byDiffRes.ok) {
            const diffData = await byDiffRes.json();
            renderAnalyticsBreakdown('by-difficulty', diffData);
        }

        // 4. Daily History & Recent Attempt Logs
        const historyRes = await fetch(`${window.API_BASE_URL}/api/analytics/history`, { headers });
        if (historyRes.ok) {
            const historyData = await historyRes.json();
            renderAnalyticsChart(historyData.daily_history || []);
            renderAnalyticsHistoryTable(historyData.recent_logs || []);
        }

    } catch (e) {
        console.error('Error fetching analytics data:', e);
    }
}

function renderAnalyticsBreakdown(mode, items, strongTypes = [], weakTypes = []) {
    const isType = mode === 'by-type';
    const containers = isType
        ? ['analytics-by-type-container', 'db-analytics-by-type-container']
        : ['analytics-by-diff-container', 'db-analytics-by-diff-container'];

    let html = '';
    if (!items || items.length === 0) {
        html = '<p style="color: var(--text-muted); font-size: 0.85rem;">No attempt records found yet.</p>';
    } else {
        items.forEach(item => {
            const title = isType ? item.challenge_type : item.difficulty;
            const accuracy = item.accuracy_percentage || 0;
            const total = item.total_attempts || 0;
            const passed = item.passed || 0;
            const avgTime = item.avg_time_taken || 0;

            let barColor = '#a855f7';
            if (accuracy >= 80) barColor = '#22c55e';
            else if (accuracy >= 50) barColor = '#f59e0b';
            else if (total > 0) barColor = '#ef4444';

            let typeBadgeHtml = '';
            if (isType) {
                if (strongTypes.includes(title)) {
                    typeBadgeHtml = `<span style="background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.35); font-size: 0.72rem; padding: 2px 8px; border-radius: 4px; font-weight: 600; margin-left: 6px;">💪 Strong Domain</span>`;
                } else if (weakTypes.includes(title)) {
                    typeBadgeHtml = `<span style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35); font-size: 0.72rem; padding: 2px 8px; border-radius: 4px; font-weight: 600; margin-left: 6px;">⚠️ Needs Practice</span>`;
                }
            }

            html += `
                <div style="background: rgba(255,255,255,0.03); padding: 12px; border-radius: 8px; border: 1px solid var(--glass-border);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 4px;">
                        <div style="display: flex; align-items: center;">
                            <span style="font-weight: 600; font-size: 0.9rem;">${title}</span>
                            ${typeBadgeHtml}
                        </div>
                        <span style="font-weight: 700; color: ${barColor}; font-size: 0.9rem;">${accuracy}% (${passed}/${total})</span>
                    </div>
                    <div style="width: 100%; height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden; margin-bottom: 6px;">
                        <div style="width: ${accuracy}%; height: 100%; background: ${barColor}; transition: width 0.4s ease;"></div>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-muted);">
                        <span>Avg Speed: ${avgTime}s</span>
                        <span>Attempts: ${total}</span>
                    </div>
                </div>
            `;
        });
    }

    containers.forEach(cid => {
        const el = document.getElementById(cid);
        if (el) el.innerHTML = html;
    });
}

function renderAnalyticsChart(dailyHistory) {
    if (typeof Chart === 'undefined') return;

    const labels = dailyHistory.length > 0 ? dailyHistory.map(d => d.date) : ['No Data'];
    const accuracyPoints = dailyHistory.length > 0 ? dailyHistory.map(d => d.accuracy_percentage) : [0];
    const passedPoints = dailyHistory.length > 0 ? dailyHistory.map(d => d.passed) : [0];

    const chartConfig = {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Accuracy (%)',
                    data: accuracyPoints,
                    borderColor: '#a855f7',
                    backgroundColor: 'rgba(168, 85, 247, 0.15)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.35,
                    pointRadius: 4,
                    pointBackgroundColor: '#a855f7'
                },
                {
                    label: 'Passed Count',
                    data: passedPoints,
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.35,
                    pointRadius: 3,
                    pointBackgroundColor: '#22c55e'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#e2e8f0', font: { family: 'Inter' } }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#94a3b8' },
                    grid: { color: 'rgba(255,255,255,0.05)' }
                },
                y: {
                    beginAtZero: true,
                    max: 100,
                    ticks: { color: '#94a3b8' },
                    grid: { color: 'rgba(255,255,255,0.05)' }
                }
            }
        }
    };

    const canvas1 = document.getElementById('analyticsAccuracyChart');
    if (canvas1) {
        if (analyticsChartInstance) analyticsChartInstance.destroy();
        analyticsChartInstance = new Chart(canvas1, chartConfig);
    }

    const canvas2 = document.getElementById('detailedSleepChart');
    if (canvas2) {
        if (dbAnalyticsChartInstance) dbAnalyticsChartInstance.destroy();
        dbAnalyticsChartInstance = new Chart(canvas2, chartConfig);
    }
}

function renderAnalyticsHistoryTable(logs) {
    const tableIds = ['analytics-history-table', 'db-analytics-history-table'];

    let rowsHtml = '';
    if (!logs || logs.length === 0) {
        rowsHtml = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">No challenge attempt logs recorded yet.</td></tr>';
    } else {
        logs.forEach(log => {
            const resBadge = log.is_correct
                ? '<span class="badge badge-success">✓ Pass</span>'
                : '<span class="badge badge-danger">✗ Fail</span>';

            rowsHtml += `
                <tr>
                    <td>${log.date || 'Just Now'}</td>
                    <td><span class="badge badge-info">${log.challenge_type || 'Math'}</span></td>
                    <td><span class="badge badge-warning">${log.difficulty || 'Medium'}</span></td>
                    <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${log.question || '-'}</td>
                    <td>${log.user_answer || '-'}</td>
                    <td>${resBadge}</td>
                    <td>${log.time_taken || 0}s / ${log.time_limit || 20}s</td>
                </tr>
            `;
        });
    }

    tableIds.forEach(tid => {
        const table = document.getElementById(tid);
        if (table) {
            const tbody = table.querySelector('tbody');
            if (tbody) tbody.innerHTML = rowsHtml;
        }
    });
}

// ==========================================================================
// REQUIREMENT 10: USER DASHBOARD & ANALYTICS CONTROLLER
// ==========================================================================

let wakeTrendChartInstance = null;
let currentAlarmHistoryFilter = '7days';
let currentWakeStatsWindow = 7;

async function loadUserDashboardOverview() {
    try {
        const response = await fetch(`${window.API_BASE_URL}/api/dashboard/overview`, {
            method: 'GET',
            headers: getAuthHeaders()
        });
        if (!response.ok) {
            console.warn('Dashboard overview fetch failed:', response.status);
            return;
        }
        const data = await response.json();

        // Update Dashboard Metric Cards
        const setTxt = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val !== null && val !== undefined ? val : '--';
        };

        setTxt('stat-total-alarms', data.total_alarms);
        setTxt('stat-active-alarms', data.active_alarms);
        setTxt('stat-completed-alarms', data.completed_alarms);
        setTxt('stat-missed-alarms', data.missed_alarms);
        setTxt('stat-snooze-count', data.snooze_count);
        setTxt('stat-wake-streak', `${data.current_streak} Days`);
        setTxt('stat-avg-wake-time', data.average_wake_up_time || '--:--');
        setTxt('stat-avg-delay', data.average_wake_up_delay_minutes !== null ? `${data.average_wake_up_delay_minutes}m` : '0.0m');
        setTxt('stat-avg-wakefulness', data.average_wakefulness_rating !== null ? `${data.average_wakefulness_rating}/5` : 'N/A');
        setTxt('stat-verif-success-rate', data.verification_success_rate !== null ? `${data.verification_success_rate}%` : '100%');
        setTxt('stat-habit-score', Math.round(data.habit_score));

        // Update Sleep Quality Metric Card
        const sqEl = document.getElementById('stat-sleep-quality');
        const sqLevelEl = document.getElementById('stat-sleep-quality-level');
        if (sqEl) {
            if (data.sleep_quality_score !== null && data.sleep_quality_score !== undefined) {
                sqEl.textContent = `${Math.round(data.sleep_quality_score)}%`;
                if (sqLevelEl) {
                    const level = data.sleep_quality_level || 'Good';
                    sqLevelEl.textContent = level;
                    sqLevelEl.className = `badge ${data.sleep_quality_score >= 75 ? 'badge-success' : (data.sleep_quality_score >= 50 ? 'badge-warning' : 'badge-danger')}`;
                }
            } else {
                sqEl.textContent = 'N/A*';
                if (sqLevelEl) {
                    sqLevelEl.textContent = 'Insufficient data';
                    sqLevelEl.className = 'badge badge-secondary';
                }
            }
        }

        // Update Habit Engine Badge if present
        const levelBadge = document.getElementById('habit-score-level');
        if (levelBadge) {
            levelBadge.textContent = data.habit_level || 'Calculating...';
            levelBadge.className = `badge ${data.habit_score >= 75 ? 'badge-success' : (data.habit_score >= 50 ? 'badge-warning' : 'badge-danger')}`;
        }

        // Also fetch detailed sleep quality breakdown asynchronously
        loadSleepQualityMetric(7);
    } catch (e) {
        console.error('Error loading dashboard overview:', e);
    }
}

async function loadSleepQualityMetric(days = 7) {
    const sqEl = document.getElementById('stat-sleep-quality');
    const sqLevelEl = document.getElementById('stat-sleep-quality-level');

    try {
        const response = await fetch(`${window.API_BASE_URL}/api/dashboard/sleep-quality?days=${days}`, {
            headers: getAuthHeaders()
        });
        if (!response.ok) {
            if (sqEl) sqEl.textContent = 'N/A*';
            if (sqLevelEl) {
                sqLevelEl.textContent = 'Insufficient data';
                sqLevelEl.className = 'badge badge-secondary';
            }
            return;
        }

        const data = await response.json();
        if (data.status === 'available' && data.score !== null && data.score !== undefined) {
            const scoreVal = Math.round(data.score);
            const levelVal = data.level || 'Good';
            if (sqEl) sqEl.textContent = `${scoreVal}%`;
            if (sqLevelEl) {
                sqLevelEl.textContent = levelVal;
                sqLevelEl.className = `badge ${scoreVal >= 75 ? 'badge-success' : (scoreVal >= 50 ? 'badge-warning' : 'badge-danger')}`;
            }

            // Update components if elements present
            const components = data.components || {};
            const setVal = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.textContent = val !== null && val !== undefined ? `${Math.round(val)}%` : '--';
            };
            setVal('sleep-quality-adherence', components.schedule_adherence);
            setVal('sleep-quality-duration', components.sleep_duration);
            setVal('sleep-quality-consistency', components.consistency);
        } else {
            if (sqEl) sqEl.textContent = 'N/A*';
            if (sqLevelEl) {
                sqLevelEl.textContent = 'Insufficient data';
                sqLevelEl.className = 'badge badge-secondary';
            }
        }
    } catch (e) {
        console.warn('Error loading sleep quality:', e);
        if (sqEl && (!sqEl.textContent || sqEl.textContent === '--')) {
            sqEl.textContent = 'N/A*';
            if (sqLevelEl) {
                sqLevelEl.textContent = 'Insufficient data';
                sqLevelEl.className = 'badge badge-secondary';
            }
        }
    }
}

async function filterAlarmHistory(filterType) {
    currentAlarmHistoryFilter = filterType;

    // Update active button state
    ['today', '7d', '30d'].forEach(f => {
        const btn = document.getElementById(`history-filter-${f}`);
        if (btn) {
            if ((f === 'today' && filterType === 'today') ||
                (f === '7d' && filterType === '7days') ||
                (f === '30d' && filterType === '30days')) {
                btn.className = 'btn btn-primary';
            } else {
                btn.className = 'btn btn-secondary';
            }
        }
    });

    await loadAlarmHistory(filterType);
}

async function applyCustomHistoryFilter() {
    const startDate = document.getElementById('history-start-date')?.value;
    const endDate = document.getElementById('history-end-date')?.value;
    if (!startDate) {
        if (typeof Toast !== 'undefined') Toast.show('Filter Range', 'Please choose a start date.', 'warning', 2500);
        return;
    }
    await loadAlarmHistory('custom', startDate, endDate);
}

async function loadAlarmHistory(filterType = '7days', startDate = '', endDate = '') {
    const tbody = document.getElementById('db-alarm-history-tbody');
    if (!tbody) return;

    try {
        let url = `${window.API_BASE_URL}/api/dashboard/alarm-history?filter_type=${encodeURIComponent(filterType)}`;
        if (startDate) url += `&start_date=${encodeURIComponent(startDate)}`;
        if (endDate) url += `&end_date=${encodeURIComponent(endDate)}`;

        const res = await fetch(url, { headers: getAuthHeaders() });
        if (!res.ok) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 20px;">Could not load alarm history.</td></tr>';
            return;
        }

        const data = await res.json();
        const records = data.history || [];

        if (records.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 24px;">No alarm history records for this period.</td></tr>';
            return;
        }

        tbody.innerHTML = records.map(r => {
            const statusBadge = r.status === 'Completed'
                ? '<span class="badge badge-success">Completed</span>'
                : (r.status === 'Missed' ? '<span class="badge badge-danger">Missed</span>' : '<span class="badge badge-info">' + r.status + '</span>');

            const verifBadge = r.verification_result === 'Passed'
                ? '<span class="badge badge-success"><i class="fas fa-check"></i> Passed</span>'
                : (r.verification_result === 'Failed' ? '<span class="badge badge-danger"><i class="fas fa-times"></i> Failed</span>' : '<span class="badge badge-secondary">' + r.verification_result + '</span>');

            const ratingDisplay = r.wakefulness_rating ? `<span style="color: #fbbf24;">★</span> ${r.wakefulness_rating}/5` : '<span style="color: var(--text-muted);">-</span>';

            return `
                <tr>
                    <td><strong>${r.alarm_label}</strong></td>
                    <td><code>${r.scheduled_time || '--:--'}</code></td>
                    <td>${r.trigger_time || '--:--'}</td>
                    <td><strong style="color: var(--primary);">${r.actual_wake_time || '--:--'}</strong></td>
                    <td>${statusBadge}</td>
                    <td>${r.snooze_count > 0 ? `<span class="badge badge-warning">${r.snooze_count}</span>` : '0'}</td>
                    <td>${verifBadge}</td>
                    <td>${ratingDisplay}</td>
                    <td><span style="font-size: 0.8rem; color: var(--text-secondary);">${r.challenge_result || '-'}</span></td>
                    <td><span style="font-size: 0.8rem; color: var(--text-muted);">${r.date}</span></td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error('Error loading alarm history:', e);
        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #ef4444; padding: 20px;">Failed to connect to history service.</td></tr>';
    }
}

async function setWakeStatsWindow(days) {
    currentWakeStatsWindow = days;
    const btn7 = document.getElementById('wake-stat-7d');
    const btn30 = document.getElementById('wake-stat-30d');
    if (btn7) btn7.className = days === 7 ? 'btn btn-primary' : 'btn btn-secondary';
    if (btn30) btn30.className = days === 30 ? 'btn btn-primary' : 'btn btn-secondary';
    await loadWakeUpStatistics(days);
}

async function loadWakeUpStatistics(days = 7) {
    const canvas = document.getElementById('wakeUpTrendChart');
    if (!canvas) return;

    try {
        const res = await fetch(`${window.API_BASE_URL}/api/dashboard/wake-up-statistics?days=${days}`, {
            headers: getAuthHeaders()
        });
        if (!res.ok) return;

        const data = await res.json();
        const points = data.trend_points || [];

        const labels = points.map(p => p.date);
        const schedData = points.map(p => p.scheduled_minutes !== null ? (p.scheduled_minutes / 60.0) : null);
        const actualData = points.map(p => p.actual_minutes !== null ? (p.actual_minutes / 60.0) : null);

        if (labels.length === 0) {
            labels.push('Today');
            schedData.push(7.0);
            actualData.push(7.0);
        }

        if (wakeTrendChartInstance) {
            wakeTrendChartInstance.destroy();
        }

        wakeTrendChartInstance = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Scheduled Wake (Hour)',
                        data: schedData,
                        borderColor: '#818cf8',
                        backgroundColor: 'rgba(129, 140, 248, 0.1)',
                        borderDash: [5, 5],
                        fill: false,
                        tension: 0.3,
                        pointRadius: 4,
                        pointBackgroundColor: '#818cf8'
                    },
                    {
                        label: 'Actual Wake (Hour)',
                        data: actualData,
                        borderColor: '#22c55e',
                        backgroundColor: 'rgba(34, 197, 94, 0.15)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 5,
                        pointBackgroundColor: '#22c55e'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: { color: '#e2e8f0', font: { family: 'Inter', size: 12 } }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                const val = ctx.raw;
                                if (val === null || val === undefined) return 'No data';
                                const totalMins = Math.round(val * 60);
                                const h = Math.floor(totalMins / 60);
                                const m = totalMins % 60;
                                return `${ctx.dataset.label}: ${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: '#94a3b8' },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    },
                    y: {
                        ticks: {
                            color: '#94a3b8',
                            callback: function(val) {
                                const h = Math.floor(val);
                                const m = Math.round((val - h) * 60);
                                return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
                            }
                        },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    }
                }
            }
        });
    } catch (e) {
        console.error('Error loading wake-up statistics:', e);
    }
}

async function loadCategorizedRecommendations() {
    const container = document.getElementById('db-recommendations-list');
    if (!container) return;

    try {
        const res = await fetch(`${window.API_BASE_URL}/api/dashboard/recommendations`, {
            headers: getAuthHeaders()
        });
        if (!res.ok) {
            container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">Recommendations service offline.</div>';
            return;
        }

        const data = await res.json();
        const recs = data.recommendations || [];

        if (recs.length === 0) {
            container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem; padding: 14px;">Complete your morning wake-up alarms to receive personalized recommendations.</div>';
            return;
        }

        const catColors = {
            'Sleep Improvement': { bg: 'rgba(99, 102, 241, 0.15)', text: '#818cf8', icon: 'fa-bed' },
            'Wake-Up Optimization': { bg: 'rgba(56, 189, 248, 0.15)', text: '#38bdf8', icon: 'fa-sun' },
            'Habit Improvement': { bg: 'rgba(168, 85, 247, 0.15)', text: '#c084fc', icon: 'fa-brain' },
            'Productivity': { bg: 'rgba(34, 197, 94, 0.15)', text: '#4ade80', icon: 'fa-chart-line' },
            'Personalized Challenge': { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', icon: 'fa-puzzle-piece' }
        };

        container.innerHTML = recs.map(r => {
            const theme = catColors[r.category] || { bg: 'rgba(255,255,255,0.1)', text: '#e2e8f0', icon: 'fa-lightbulb' };
            const priorityBadge = r.priority === 'High'
                ? '<span class="badge badge-danger">High Priority</span>'
                : (r.priority === 'Medium' ? '<span class="badge badge-warning">Medium</span>' : '<span class="badge badge-info">Low</span>');

            return `
                <div class="glass-card" style="padding: 14px; background: rgba(15, 23, 42, 0.35); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; display: flex; flex-direction: column; justify-content: space-between; gap: 8px;">
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <span class="badge" style="background: ${theme.bg}; color: ${theme.text}; font-size: 0.72rem; border-radius: 6px; padding: 3px 8px;">
                                <i class="fas ${theme.icon}" style="margin-right: 4px;"></i> ${r.category}
                            </span>
                            ${priorityBadge}
                        </div>
                        <h4 style="margin: 0 0 4px; font-size: 0.95rem; color: #fff;">${r.title}</h4>
                        <p style="margin: 0; font-size: 0.82rem; color: var(--text-secondary); line-height: 1.5;">${r.message}</p>
                    </div>
                    <div style="font-size: 0.72rem; color: var(--text-muted); border-top: 1px solid rgba(255,255,255,0.05); padding-top: 6px; margin-top: 4px;">
                        <i class="fas fa-info-circle"></i> Reason: ${r.reason}
                    </div>
                </div>
            `;
        }).join('');

        if (recs.length > 0) {
            const tipEl = document.getElementById('dashboard-adaptive-tip');
            if (tipEl) {
                tipEl.textContent = `${recs[0].title}: ${recs[0].message}`;
            }
        }
    } catch (e) {
        console.error('Error loading recommendations:', e);
    }
}

async function loadChallengePerformanceMetrics() {
    try {
        const res = await fetch(`${window.API_BASE_URL}/api/dashboard/challenge-performance`, {
            headers: getAuthHeaders()
        });
        if (!res.ok) return;

        const data = await res.json();

        // Update Overview Cards if on Analytics page
        const setTxt = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val !== null && val !== undefined ? val : '0';
        };

        setTxt('analytics-accuracy', `${data.overall_accuracy}%`);
        setTxt('analytics-passed', data.completed_challenges);
        setTxt('analytics-failed', data.incorrect_answers);
        setTxt('analytics-avg-time', `${data.average_completion_time}s`);

        setTxt('db-analytics-accuracy', `${data.overall_accuracy}%`);
        setTxt('db-analytics-passed', data.completed_challenges);
        setTxt('db-analytics-failed', data.incorrect_answers);
        setTxt('db-analytics-avg-time', `${data.average_completion_time}s`);

        // Render By Type breakdown
        const renderByType = (containerId) => {
            const container = document.getElementById(containerId);
            if (!container) return;

            const types = data.performance_by_type || [];
            if (types.length === 0) {
                container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">No attempts recorded yet.</div>';
                return;
            }

            container.innerHTML = types.map(t => `
                <div style="background: rgba(255,255,255,0.03); padding: 10px 12px; border-radius: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; font-size: 0.85rem;">
                        <span style="color: #fff; font-weight: 600;">${t.challenge_type}</span>
                        <span style="color: var(--primary); font-weight: 700;">${t.accuracy_percentage}% <span style="font-size: 0.75rem; color: var(--text-muted);">(${t.passed}/${t.total_attempts})</span></span>
                    </div>
                    <div class="progress-bar-container" style="height: 5px; background: rgba(255,255,255,0.08); border-radius: 3px;">
                        <div class="progress-bar-fill" style="width: ${t.accuracy_percentage}%; background: var(--primary);"></div>
                    </div>
                </div>
            `).join('');
        };

        renderByType('analytics-by-type-container');
        renderByType('db-analytics-by-type-container');

        // Render By Difficulty breakdown
        const renderByDiff = (containerId) => {
            const container = document.getElementById(containerId);
            if (!container) return;

            const diffs = data.performance_by_difficulty || [];
            if (diffs.length === 0) {
                container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">No attempts recorded yet.</div>';
                return;
            }

            container.innerHTML = diffs.map(d => `
                <div style="background: rgba(255,255,255,0.03); padding: 10px 12px; border-radius: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; font-size: 0.85rem;">
                        <span style="color: #fff; font-weight: 600;">${d.difficulty}</span>
                        <span style="color: #22c55e; font-weight: 700;">${d.accuracy_percentage}% <span style="font-size: 0.75rem; color: var(--text-muted);">(${d.passed}/${d.total_attempts})</span></span>
                    </div>
                    <div class="progress-bar-container" style="height: 5px; background: rgba(255,255,255,0.08); border-radius: 3px;">
                        <div class="progress-bar-fill" style="width: ${d.accuracy_percentage}%; background: #22c55e;"></div>
                    </div>
                </div>
            `).join('');
        };

        renderByDiff('analytics-by-diff-container');
        renderByDiff('db-analytics-by-diff-container');

        // Update Daily Accuracy Chart
        if (data.daily_trend && data.daily_trend.length > 0) {
            renderAnalyticsChart(data.daily_trend);
        }
    } catch (e) {
        console.error('Error loading challenge performance metrics:', e);
    }
}

async function loadProductivityInsightsData() {
    try {
        const res = await fetch(`${window.API_BASE_URL}/api/dashboard/productivity-insights`, {
            headers: getAuthHeaders()
        });
        if (!res.ok) return;

        const data = await res.json();
        const insights = data.insights || [];

        const renderList = (id) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (insights.length === 0) {
                el.innerHTML = '<li>Insufficient data to calculate productivity correlations yet.</li>';
            } else {
                el.innerHTML = insights.map(ins => `<li>${ins}</li>`).join('');
            }
        };

        renderList('behavior-insights-list');
        renderList('db-behavior-insights-list');
    } catch (e) {
        console.error('Error loading productivity insights:', e);
    }
}

// Master loader triggered on page mount, tab change, or alarm verification completion
async function refreshAllDashboardAnalytics() {
    await Promise.allSettled([
        loadUserDashboardOverview(),
        loadAlarmHistory('7days'),
        loadWakeUpStatistics(7),
        loadCategorizedRecommendations(),
        loadChallengePerformanceMetrics(),
        loadProductivityInsightsData(),
        loadHabitScoreData(7)
    ]);
}

// Attach live refresh to DOM ready and tab switches
window.addEventListener('DOMContentLoaded', () => {
    refreshAllDashboardAnalytics();
});

// Guard and export refresh hook for verification service
window.refreshAllDashboardAnalytics = refreshAllDashboardAnalytics;
window.filterAlarmHistory = filterAlarmHistory;
window.applyCustomHistoryFilter = applyCustomHistoryFilter;
window.setWakeStatsWindow = setWakeStatsWindow;
window.loadCategorizedRecommendations = loadCategorizedRecommendations;

// Multi-Format Personal Sleep & Habit Document Export (PDF, Excel, CSV)
window.exportUserReport = async (format = 'pdf') => {
    const fmt = (format || 'pdf').toLowerCase();
    Toast.show('Compiling Personal Report...', `Generating ${fmt.toUpperCase()} export from PostgreSQL records.`, 'info', 2000);

    const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
    let alarms = [];
    let wakeStats = null;
    let habitData = null;

    try {
        const [aRes, wRes, hRes] = await Promise.allSettled([
            fetch(`${window.API_BASE_URL}/api/alarms`, { headers: getAuthHeaders() }),
            fetch(`${window.API_BASE_URL}/api/dashboard/wake-statistics?days=30`, { headers: getAuthHeaders() }),
            fetch(`${window.API_BASE_URL}/api/dashboard/habit-score?days=30`, { headers: getAuthHeaders() })
        ]);

        if (aRes.status === 'fulfilled' && aRes.value.ok) {
            const json = await aRes.value.json();
            alarms = Array.isArray(json) ? json : (json.alarms || []);
        }
        if (wRes.status === 'fulfilled' && wRes.value.ok) wakeStats = await wRes.value.json();
        if (hRes.status === 'fulfilled' && hRes.value.ok) habitData = await hRes.value.json();
    } catch (_) {}

    const dateStr = new Date().toLocaleDateString();
    const timeStr = new Date().toLocaleTimeString();

    if (fmt === 'csv') {
        let csv = '\uFEFF';
        csv += 'WAKEWISE AI - PERSONAL SLEEP & HABIT PERFORMANCE REPORT\r\n';
        csv += `Export Date,${dateStr} ${timeStr}\r\n`;
        csv += `User Name,"${(session.name || 'User').replace(/"/g, '""')}"\r\n`;
        csv += `Email,"${(session.email || '').replace(/"/g, '""')}"\r\n`;
        csv += `Habit Score,${habitData ? (habitData.overall_habit_score || habitData.habit_score || 0) : 0}%\r\n`;
        csv += `Total Active Alarms,${alarms.filter(a => a.is_active).length}\r\n\r\n`;

        csv += '--- CONFIGURED ALARMS ---\r\n';
        csv += 'Alarm Title,Time,Repeat Days,Type,Status,Verification Method,Tone\r\n';
        alarms.forEach(a => {
            csv += `"${(a.title || 'Alarm').replace(/"/g, '""')}","${a.alarm_time}","${a.repeat_days || ''}","${a.alarm_type || 'standard'}","${a.is_active ? 'Active' : 'Disabled'}","${a.verification_method || 'multi_step'}","${a.alarm_tone || 'Standard'}"\r\n`;
        });
        csv += '\r\n';

        csv += '--- WAKE-UP PERFORMANCE SUMMARY ---\r\n';
        csv += 'Metric,Value\r\n';
        csv += `Total Scheduled Alarms,${wakeStats ? (wakeStats.total_alarms || 0) : alarms.length}\r\n`;
        csv += `On-Time Wake Ratio,${wakeStats ? (wakeStats.on_time_ratio_pct || 0) : 0}%\r\n`;
        csv += `Average Snooze Count,${wakeStats ? (wakeStats.average_snoozes || 0) : 0}\r\n`;
        csv += `Challenges Completed,${wakeStats ? (wakeStats.challenges_completed || 0) : 0}\r\n`;

        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `WakeWise_User_Report_${Date.now()}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        Toast.show('CSV Downloaded', 'Personal sleep ledger CSV saved successfully.', 'success', 2500);

    } else if (fmt === 'excel' || fmt === 'xlsx' || fmt === 'xls') {
        let excel = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:html="http://www.w3.org/TR/REC-html40">
 <Styles>
  <Style ss:ID="Header"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#107C41" ss:Pattern="Solid"/></Style>
  <Style ss:ID="Title"><Font ss:Bold="1" ss:Size="14" ss:Color="#107C41"/></Style>
  <Style ss:ID="Subheader"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#16A34A" ss:Pattern="Solid"/></Style>
 </Styles>
 <Worksheet ss:Name="Sleep Performance">
  <Table>
   <Row><Cell ss:StyleID="Title"><Data ss:Type="String">WakeWise AI - Personal Sleep & Habit Performance</Data></Cell></Row>
   <Row><Cell><Data ss:Type="String">User: ${escapeXmlReport(session.name || 'User')} (${escapeXmlReport(session.email || '')})</Data></Cell></Row>
   <Row><Cell><Data ss:Type="String">Generated: ${dateStr} ${timeStr}</Data></Cell></Row>
   <Row><Cell><Data ss:Type="String">Overall Habit Score: ${habitData ? (habitData.overall_habit_score || habitData.habit_score || 0) : 0}%</Data></Cell></Row>
   <Row></Row>
   <Row ss:StyleID="Subheader"><Cell><Data ss:Type="String">Configured Alarms</Data></Cell></Row>
   <Row ss:StyleID="Header">
    <Cell><Data ss:Type="String">Alarm Title</Data></Cell>
    <Cell><Data ss:Type="String">Time</Data></Cell>
    <Cell><Data ss:Type="String">Repeat Days</Data></Cell>
    <Cell><Data ss:Type="String">Type</Data></Cell>
    <Cell><Data ss:Type="String">Verification Method</Data></Cell>
    <Cell><Data ss:Type="String">Status</Data></Cell>
   </Row>`;

        alarms.forEach(a => {
            excel += `
   <Row>
    <Cell><Data ss:Type="String">${escapeXmlReport(a.title || 'Alarm')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXmlReport(a.alarm_time || '')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXmlReport(a.repeat_days || 'Daily')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXmlReport(a.alarm_type || 'standard')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXmlReport(a.verification_method || 'multi_step')}</Data></Cell>
    <Cell><Data ss:Type="String">${a.is_active ? 'Active' : 'Disabled'}</Data></Cell>
   </Row>`;
        });

        excel += `
  </Table>
 </Worksheet>
</Workbook>`;

        const blob = new Blob([excel], { type: 'application/vnd.ms-excel;charset=utf-8;' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `WakeWise_User_Report_${Date.now()}.xls`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        Toast.show('Excel Downloaded', 'Spreadsheet report saved successfully.', 'success', 2500);

    } else {
        // PDF format
        const printWindow = window.open('', '_blank', 'width=860,height=700');
        if (!printWindow) {
            Toast.show('Popup Blocked', 'Please allow popups to generate PDF report.', 'warning', 3000);
            return;
        }

        const html = `<!DOCTYPE html>
<html>
<head>
    <title>WakeWise AI - Personal Sleep & Habit Performance</title>
    <style>
        @page { size: A4; margin: 16mm; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1e293b; margin: 0; padding: 20px; font-size: 12px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #6366f1; padding-bottom: 12px; margin-bottom: 20px; }
        .logo { font-size: 20px; font-weight: 700; color: #6366f1; }
        .meta { text-align: right; font-size: 11px; color: #64748b; }
        .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 24px; }
        .stat-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; text-align: center; }
        .stat-box h4 { margin: 0; font-size: 18px; color: #1e1b4b; }
        .stat-box p { margin: 4px 0 0; font-size: 11px; color: #64748b; }
        h3 { font-size: 14px; margin: 20px 0 8px; color: #334155; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 11px; }
        th, td { border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; }
        th { background: #f1f5f9; font-weight: 600; color: #475569; }
        tr:nth-child(even) { background: #fafafa; }
        .footer { margin-top: 30px; text-align: center; font-size: 10px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 10px; }
        @media print { body { padding: 0; } }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <div class="logo">🧠 WakeWise AI - Personal Summary</div>
            <div style="font-size: 12px; color: #475569; margin-top: 4px;">Sleep, Wake, and Cognitive Habit Report</div>
        </div>
        <div class="meta">
            <div><strong>User:</strong> ${escapeXmlReport(session.name || 'User')} (${escapeXmlReport(session.email || '')})</div>
            <div><strong>Date:</strong> ${dateStr} ${timeStr}</div>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-box">
            <h4>${habitData ? (habitData.overall_habit_score || habitData.habit_score || 0) : 0}%</h4>
            <p>Overall Habit Score</p>
        </div>
        <div class="stat-box">
            <h4>${alarms.length}</h4>
            <p>Configured Alarms</p>
        </div>
        <div class="stat-box">
            <h4>${wakeStats ? (wakeStats.on_time_ratio_pct || 100) : 100}%</h4>
            <p>On-Time Wake Ratio</p>
        </div>
    </div>

    <h3>Configured Wake-Up Alarms (${alarms.length})</h3>
    <table>
        <thead>
            <tr>
                <th>Alarm Title</th>
                <th>Time</th>
                <th>Repeat</th>
                <th>Type</th>
                <th>Verification</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            ${alarms.length === 0 ? '<tr><td colspan="6" style="text-align:center;">No alarms configured.</td></tr>' : alarms.map(a => `
                <tr>
                    <td><strong>${escapeXmlReport(a.title || 'Alarm')}</strong></td>
                    <td>${a.alarm_time}</td>
                    <td>${escapeXmlReport(a.repeat_days || 'Daily')}</td>
                    <td>${escapeXmlReport(a.alarm_type || 'standard')}</td>
                    <td>${escapeXmlReport(a.verification_method || 'multi_step')}</td>
                    <td>${a.is_active ? 'Active' : 'Disabled'}</td>
                </tr>
            `).join('')}
        </tbody>
    </table>

    <div class="footer">
        WakeWise AI Personal Sleep Report • Generated from live PostgreSQL Database
    </div>

    <script>
        window.onload = function() {
            setTimeout(function() { window.print(); }, 300);
        };
    </script>
</body>
</html>`;

        printWindow.document.open();
        printWindow.document.write(html);
        printWindow.document.close();
        Toast.show('PDF Ready', 'Print dialog opened. Select "Save as PDF".', 'success', 2500);
    }
};

window.simulateUserExport = (fmt) => window.exportUserReport(fmt || 'pdf');

function escapeXmlReport(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

// Anti-bypass window guard: prevent closing/reloading while verification is active
window.addEventListener('beforeunload', (e) => {
    if (window.currentRingingAlarm && window.isWakeUpVerified !== true) {
        e.preventDefault();
        e.returnValue = 'Wake-Up Verification in progress! Complete the challenge to silence the alarm.';
        return e.returnValue;
    }
});