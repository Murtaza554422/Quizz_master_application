import streamlit as st
from backend import (
    extract_text_from_pdf,
    chunk_text,
    generate_quiz_from_text,
    evaluate_answers,
)

# ---------------- Page Setup ----------------
st.set_page_config(page_title="Quiz Master", layout="wide", page_icon="📚")

# ---------------- Custom CSS ----------------

st.markdown(
    """
    <style>
      .app-hero {
        background: linear-gradient(135deg, #eef5ff 0%, #ffffff 100%);
        border: 1px solid #e6eefc;
        border-radius: 16px;
        padding: 24px;
        box-shadow: 0 6px 20px rgba(30, 60, 114, 0.06);
      }
      .card {
        background: #ffffff;
        border: 0.2px solid #edf0f6;
        border-radius: 8px;
        padding: 8px 9px;
        margin-bottom: 7px;
        box-shadow: 0 4px 14px rgba(16, 24, 40, 0.04);
      }
      .cta > button {
        width: 100%;
        height: 48px;
        border-radius: 12px !important;
        font-weight: 600 !important;
        font-size: 16px !important;
      }
      .submit-btn > button {
        width: 100%;
        border-radius: 12px !important;
        font-weight: 600 !important;
      }
      .metric-pill {
        display: inline-block;
        padding: 6px 12px;
        border-radius: 999px;
        background: #f1f5ff;
        color: #274690;
        font-weight: 600;
        border: 1px solid #dbe6ff;
      }
      .level-desc {
        color: #475467;
        font-size: 14px;
        margin-top: -8px;
        margin-bottom: 8px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------- Sidebar (Uploader + Settings) ----------------
with st.sidebar:
    st.header("📄 Upload & Settings")

    st.markdown(
        """
        **Start here:** Upload your PDF and pick how many questions per level.
        """
    )

    pdf_file = st.file_uploader("📂 Upload PDF", type=["pdf"])

    st.divider()
    st.caption("Chunking controls how much context is sent to the model.")
    chunk_size = st.slider("Chunk size", 800, 2400, 1200, 100)
    chunk_overlap = st.slider("Chunk overlap", 100, 600, 240, 20)

    st.divider()
    n_per_level = st.slider("Questions per level", 3, 8, 5, 1)

    st.divider()
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        generate_btn = st.button("🚀 Generate Quiz", type="primary")
    with col_g2:
        reset_btn = st.button("🧹 Reset")

    if reset_btn:
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ---------------- Session State ----------------
st.session_state.setdefault("quiz_data", None)           # dict with basic/intermediate/hard
st.session_state.setdefault("user_answers", {})          # {"level_i": "A|B|C|D"}
st.session_state.setdefault("submitted_q", {})           # {"level_i": True}
st.session_state.setdefault("results_cache", None)       # (score, feedback)
st.session_state.setdefault("material_info", "")         # info banner text

# ---------------- Main: Welcome / Overview ----------------
st.title("📚 Quiz Master")



# ---------------- Generate Quiz Pipeline ----------------
if generate_btn:
    if not pdf_file:
        st.error("Please upload a PDF first from the left sidebar.")
    else:
        with st.spinner("📖 Extracting text from PDF..."):
            try:
                full_text = extract_text_from_pdf(pdf_file)
                if not full_text.strip():
                    st.error("No extractable text found in the uploaded PDF.")
                else:
                    chunks = chunk_text(full_text, chunk_size=chunk_size, overlap=chunk_overlap)
                    material = " ".join(chunks[:3]) if len(chunks) > 3 else " ".join(chunks)
                    st.session_state.material_info = f"Using {len(chunks)} chunks. Sent {min(3, len(chunks))} chunk(s) to the model."
            except Exception as e:
                st.exception(e)
                material = ""

        if material:
            with st.spinner("🤖 Generating quiz (this may take a few seconds)..."):
                try:
                    quiz_data = generate_quiz_from_text(
                        content=material,
                        questions_per_level=n_per_level,
                    )
                    st.session_state.quiz_data = quiz_data
                    st.session_state.user_answers = {}
                    st.session_state.submitted_q = {}
                    st.session_state.results_cache = None
                    st.success("✅ Quiz generated successfully!")
                except Exception as e:
                    st.error("❌ Quiz generation failed.")
                    with st.expander("Show error details"):
                        st.exception(e)
                    st.session_state.quiz_data = None
                    st.session_state.results_cache = None

# ---------------- If we have a quiz: render interface ----------------
quiz = st.session_state.get("quiz_data")
if quiz:
    st.info(st.session_state.material_info)

    # Progress tracker (answered + score so far)
    total_questions = sum(len(quiz[lvl]) for lvl in ["basic", "intermediate", "hard"])
    answered_questions = len(st.session_state.submitted_q)
    # Provisional score: count correct in user_answers vs quiz
    provisional_score = 0
    for level in ["basic", "intermediate", "hard"]:
        for i, q in enumerate(quiz[level]):
            key = f"{level}_{i}"
            if key in st.session_state.submitted_q and key in st.session_state.user_answers:
                # compare with ground truth
                if st.session_state.user_answers[key] == q["correct"]:
                    provisional_score += 1

    st.subheader("📝 Take Your Quiz")
    pb = st.progress(answered_questions / total_questions if total_questions else 0.0)
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Answered", f"{answered_questions} / {total_questions}")
    col_m2.metric("Score (so far)", f"{provisional_score}")
    col_m3.metric("Remaining", f"{total_questions - answered_questions}")

    st.caption("Submit each question to lock your answer and see immediate feedback.")

    # Render each level with cards
    for level in ["basic", "intermediate", "hard"]:
        st.markdown(f"### {level.capitalize()} Level")
        for i, q in enumerate(quiz[level]):
            key = f"{level}_{i}"
            submitted = st.session_state.submitted_q.get(key, False)

            with st.container():
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"**Q{i+1}. {q['question']}**")

                # Options as letters, but show text via format_func
                option_keys = ["A", "B", "C", "D"]

                def _fmt(opt_key: str, _q=q):
                    return f"{opt_key}: {_q['options'][opt_key]}"

                selected = st.radio(
                   f"Select your answer (Question {i+1})",
                    option_keys,
                    format_func=_fmt,
                    key=key,
                    index=None,   # 👈 prevents pre-selecting "A"
                    disabled=submitted,
                )
               
                c1, c2 = st.columns([1, 1])
                with c1:
                    # Per-question submit button
                    if st.button("Submit Answer ✅", key=f"submit_{key}", type="primary", use_container_width=True, disabled=submitted):
                        # Lock this question, record answer
                        st.session_state.submitted_q[key] = True
                        # Immediate feedback
                        if selected == q["correct"]:
                            st.success("Correct! 🎉")
                        else:
                            st.error(f"Wrong. Correct answer: {q['correct']}: {q['options'][q['correct']]}")
                            st.info(f"Why: {q['explanation']}")
                with c2:
                    # Allow change (until submitted)
                    st.button("Clear Selection 🧽", key=f"clear_{key}", use_container_width=True, disabled=submitted, on_click=lambda k=key: st.session_state.__setitem__(k, None))

                # If already submitted, show the feedback persistently
                if submitted:
                    if st.session_state.user_answers.get(key, selected) == q["correct"]:
                        st.success("You answered this correctly. ✅")
                    else:
                        st.error(f"Your answer was incorrect. ❌ Correct: {q['correct']}: {q['options'][q['correct']]}")
                        st.info(f"Why: {q['explanation']}")

                st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # Final submit/evaluate
    # Ensure user_answers contains the (locked) selected values
    for k in st.session_state.submitted_q.keys():
        st.session_state.user_answers[k] = st.session_state.get(k)

    col_f1, col_f2, col_f3 = st.columns([1, 1, 1])
    with col_f1:
        finish = st.button("📤 Finish & See Results", type="primary", use_container_width=True)
    with col_f2:
        st.button("🔄 Retry (keep PDF & settings)", use_container_width=True, on_click=lambda: (
            st.session_state.update({"quiz_data": None, "user_answers": {}, "submitted_q": {}, "results_cache": None})
        ))
    with col_f3:
        st.button("🧼 Start Over (reset all)", use_container_width=True, on_click=lambda: (
            [st.session_state.pop(k) for k in list(st.session_state.keys())]  # wipe
        ))

    if finish:
        # Evaluate on whatever has been answered (unanswered counted as wrong)
        score, feedback = evaluate_answers(st.session_state.user_answers, quiz)
        st.session_state.results_cache = (score, feedback)

# ---------------- Results Page ----------------
if st.session_state.get("results_cache"):
    score, feedback = st.session_state.results_cache
    quiz = st.session_state.quiz_data
    total_questions = sum(len(quiz[lvl]) for lvl in ["basic", "intermediate", "hard"]) if quiz else 0
    pct = (score / total_questions) if total_questions else 0

    st.header("📊 Results")
    st.metric("Total Score", f"{score} / {total_questions}")
    st.progress(pct)

    # Breakdown per level
    with st.expander("Breakdown & Feedback"):
        for fb in feedback:
            st.write(f"**Q:** {fb['question']}")
            st.write(f"**Result:** {fb['result']}")
            st.write(f"**Explanation:** {fb['explanation']}")
            st.write("---")

    # Suggestions for improvement
    if pct < 0.5:
        st.warning("Suggestion: Review the basics section and try smaller chunk size for clearer questions.")
    elif pct < 0.8:
        st.info("Good job! Re-try Intermediate/Hard levels to reinforce understanding.")
    else:
        st.success("Excellent! Consider increasing questions per level for a greater challenge.")
