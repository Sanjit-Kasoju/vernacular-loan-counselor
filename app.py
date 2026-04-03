"""
app.py  -  Streamlit UI for the Vernacular Loan Counselor
           Run with:  streamlit run app.py
"""

import uuid
import hashlib
import streamlit as st
from audio_recorder_streamlit import audio_recorder

from backend.llm_brain import LoanCounselorBrain
from backend.voice     import transcribe_audio, synthesize_speech
from backend.rag       import RAGSystem
from backend.database  import client as supabase_client

st.set_page_config(page_title="HomeFirst – Loan Counselor", page_icon="🏠", layout="wide")

st.markdown("""
<style>

    .chat-bubble-user {
        background: #dbeafe; border-radius: 12px 12px 0 12px;
        padding: 10px 14px; margin: 6px 0; max-width: 80%; margin-left: auto;
        text-align: right; color: #1e3a8a;
    }
    .chat-bubble-bot {
        background: #ffffff; border-radius: 12px 12px 12px 0;
        padding: 10px 14px; margin: 6px 0; max-width: 80%;
        box-shadow: 0 1px 4px rgba(0,0,0,0.1); color: #1a1a1a;
    }
    .handoff-banner {
        background: linear-gradient(90deg, #ff6b35, #f7931e);
        color: white; padding: 14px 20px; border-radius: 8px;
        font-weight: bold; text-align: center; margin-bottom: 12px;
    }
</style>
""", unsafe_allow_html=True)

# ─── Session state ─────────────────────────────────────────────────────────────
if "brain" not in st.session_state:
    st.session_state.brain            = LoanCounselorBrain()
    st.session_state.rag              = RAGSystem()
    st.session_state.session_id       = str(uuid.uuid4())[:8]
    st.session_state.messages         = []
    st.session_state.handoff_done     = False
    st.session_state.debug_info       = {}
    st.session_state.last_audio       = None
    st.session_state.last_audio_hash  = ""   # MD5 of last processed recording
    st.session_state.processing       = False # guard against double-submit

brain      = st.session_state.brain
rag_system = st.session_state.rag


def get_stt_language() -> str:
    # After lock: use the locked language directly
    # Before lock: use hindi (most common Indian language)
    # Sarvam with hi-IN transcribes Hindi speech correctly into Devanagari
    # which Gemini can then detect accurately as hindi.
    # English speech transcribed with hi-IN comes out as Latin script too
    # (e.g. "I need a loan") which Gemini still detects as english correctly.
    return brain.locked_language if brain.locked_language else "hindi"


def process_message(user_text: str):
    if not user_text.strip():
        return
    rag_ctx   = rag_system.retrieve(user_text)
    result    = brain.chat(user_text, rag_context=rag_ctx)
    bot_reply = result["response_text"]
    language  = result["language"]

    st.session_state.messages.append(("user",      user_text))
    st.session_state.messages.append(("assistant", bot_reply))
    st.session_state.debug_info = result

    if result["handoff"] and not st.session_state.handoff_done:
        st.session_state.handoff_done = True

    try:
        st.session_state.last_audio = synthesize_speech(bot_reply, language)
    except Exception as e:
        st.session_state.last_audio = None
        st.warning(f"⚠️ Voice reply unavailable: {e}")


# ─── Layout ────────────────────────────────────────────────────────────────────
st.title("🏠 HomeFirst – Vernacular Loan Counselor")
st.caption("Speak or type in English, Hindi, Marathi, or Tamil — language auto-detected from first message.")

main_col, debug_col = st.columns([3, 1])

with main_col:

    if st.session_state.handoff_done:
        st.markdown('<div class="handoff-banner">🎉 HANDOFF TRIGGERED — Connecting to Human RM...</div>',
                    unsafe_allow_html=True)

    # Chat history
    for role, text in st.session_state.messages:
        css = "chat-bubble-user" if role == "user" else "chat-bubble-bot"
        icon = "🧑" if role == "user" else "🤖"
        st.markdown(f'<div class="{css}">{icon} {text}</div>', unsafe_allow_html=True)

    if not st.session_state.messages:
        st.info("👋 Just start speaking or typing — in English, Hindi, Marathi, or Tamil.\n\n"
                "Your language will be auto-detected from your first message and locked forever.")

    # Audio player
    if st.session_state.last_audio:
        st.markdown("🔊 **Vaani is speaking:**")
        st.audio(st.session_state.last_audio, format="audio/wav", autoplay=True)

    st.divider()

    # ── Tabs ───────────────────────────────────────────────────────────────────
    input_tab, voice_tab = st.tabs(["⌨️ Type Message", "🎙️ Voice (Push-to-Talk)"])

    with input_tab:
        user_input = st.text_input("Message",
                                   placeholder="Type in English, Hindi, Marathi or Tamil...",
                                   label_visibility="collapsed", key="text_box")
        c1, c2, = st.columns([2,1])
        with c1:
            if st.button("📤 Send", use_container_width=True, type="primary"):
                if user_input.strip():
                    with st.spinner("⏳ Vaani is thinking..."):
                        process_message(user_input)
                    st.rerun()
        with c2:
            if st.button("🔄 Reset", use_container_width=True):
                brain.reset()
                st.session_state.messages        = []
                st.session_state.handoff_done    = False
                st.session_state.debug_info      = {}
                st.session_state.last_audio      = None
                st.session_state.last_audio_hash = ""
                st.session_state.processing      = False
                st.rerun()

    with voice_tab:
        locked = brain.locked_language
        if locked:
            st.success(f"🔒 Language locked to **{locked.title()}**. Speak in {locked.title()}.")
        else:
            st.info("🎙️ Speak your first message clearly — language will be auto-detected.")

        audio_bytes = audio_recorder(
            text="🔴 Click to Record",
            recording_color="#e74c3c",
            neutral_color="#3498db",
            icon_name="microphone",
            pause_threshold=2.5,
            key="audio_recorder",
        )

        # ── Anti-loop guard ────────────────────────────────────────────────────
        # audio_recorder returns the SAME bytes on every Streamlit rerun until
        # a new recording is made. We hash the bytes and skip if already processed.
        if audio_bytes and not st.session_state.processing:
            audio_hash = hashlib.md5(audio_bytes).hexdigest()

            if audio_hash != st.session_state.last_audio_hash:
                # New recording — process it
                st.session_state.last_audio_hash = audio_hash
                st.session_state.processing      = True

                stt_lang = get_stt_language()
                st.write(f"🔊 Recorded {len(audio_bytes):,} bytes. Transcribing in **{stt_lang}**...")

                try:
                    transcript = transcribe_audio(audio_bytes, language=stt_lang)
                    if transcript.strip():
                        st.success(f"**You said:** {transcript}")
                        with st.spinner("⏳ Vaani is thinking..."):
                            process_message(transcript)
                    else:
                        st.warning("Could not hear clearly — please try again.")
                except Exception as e:
                    st.error(f"STT Error: {e}")
                finally:
                    st.session_state.processing = False

                st.rerun()


# ─── Debug panel ───────────────────────────────────────────────────────────────
with debug_col:
    st.subheader("🔍 Debug Panel")
    debug = st.session_state.debug_info

    lang = brain.locked_language
    lang_color = {"english": "🟦", "hindi": "🟩", "marathi": "🟧", "tamil": "🟥"}.get(lang, "⬜")
    st.markdown(f"**Language:** {lang_color} `{lang or 'detecting...'}` {'🔒' if lang else '⏳'}")

    st.markdown("**Extracted Entities:**")
    ed = brain.extracted_data
    for label, key in [
        ("💰 Monthly Income",  "monthly_income"),
        ("🏠 Property Value",  "property_value"),
        ("📋 Loan Requested",  "loan_amount_requested"),
        ("👔 Employment",      "employment_status"),
    ]:
        val = ed.get(key)
        st.write(f"{label}: `{val}`" if val else f"{label}: —")

    tool = debug.get("tool_called")
    st.markdown(f"**Tool Called:** `{'✅ ' + tool if tool else '❌ None'}`")

    if debug.get("tool_result"):
        st.markdown("**Tool Result:**")
        for k, v in debug["tool_result"].items():
            if k == "eligible":
                st.write(f"{'✅' if v else '❌'} Eligible: `{v}`")
            elif k == "lead_score":
                c = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(v, "⚪")
                st.write(f"{c} Lead Score: `{v}`")
            elif k != "reason":
                st.write(f"• {k}: `{v}`")
        if "reason" in debug["tool_result"]:
            with st.expander("📝 Reason"):
                st.write(debug["tool_result"]["reason"])

    st.divider()
    if st.session_state.handoff_done:
        st.success("🤝 **HANDOFF TRIGGERED**")
    else:
        st.info("Waiting for high-intent lead...")
    st.caption(f"Session: `{st.session_state.session_id}`")
