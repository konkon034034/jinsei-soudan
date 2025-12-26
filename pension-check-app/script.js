document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const screens = {
        welcome: document.getElementById('welcome-screen'),
        quiz: document.getElementById('quiz-screen'),
        loading: document.getElementById('loading-screen'),
        result: document.getElementById('result-screen')
    };

    const startBtn = document.getElementById('start-btn');
    const questionText = document.getElementById('question-text');
    const optionsContainer = document.getElementById('options-container');
    const progressFill = document.getElementById('progress-fill');

    // Result Elements
    const resultRank = document.getElementById('result-rank');
    const resultTitle = document.getElementById('result-title');
    const resultMessage = document.getElementById('result-message');
    const affiliateLink = document.getElementById('affiliate-link');

    // State
    let currentQuestionIndex = 0;
    let totalScore = 0;

    // Initialize
    startBtn.addEventListener('click', startQuiz);

    function switchScreen(screenName) {
        // Hide all screens
        Object.values(screens).forEach(screen => screen.classList.add('hidden'));
        // Show target screen
        screens[screenName].classList.remove('hidden');
        screens[screenName].classList.add('fade-in');
    }

    function startQuiz() {
        currentQuestionIndex = 0;
        totalScore = 0;
        switchScreen('quiz');
        renderQuestion();
    }

    function renderQuestion() {
        const question = questions[currentQuestionIndex];

        // Update Progress Bar
        const progress = ((currentQuestionIndex) / questions.length) * 100;
        progressFill.style.width = `${progress}%`;

        // Update Text
        questionText.textContent = `Q${currentQuestionIndex + 1}. ${question.text}`;

        // Clear previous options
        optionsContainer.innerHTML = '';

        // Generate Options
        question.options.forEach(option => {
            const btn = document.createElement('button');
            btn.className = 'option-btn';
            btn.textContent = option.text;
            btn.onclick = () => handleAnswer(option.score);
            optionsContainer.appendChild(btn);
        });
    }

    function handleAnswer(score) {
        totalScore += score;
        currentQuestionIndex++;

        if (currentQuestionIndex < questions.length) {
            // Slight delay for UX
            setTimeout(renderQuestion, 200);
        } else {
            finishQuiz();
        }
    }

    function finishQuiz() {
        switchScreen('loading');

        // Final progress bar update
        progressFill.style.width = '100%';

        // Simulate calculation time
        setTimeout(() => {
            showResult();
        }, 2000);
    }

    function showResult() {
        let resultData;

        // Determine Rank
        if (totalScore >= results.rankA.minScore) {
            resultData = results.rankA;
        } else if (totalScore >= results.rankB.minScore) {
            resultData = results.rankB;
        } else {
            resultData = results.rankC;
        }

        // Render Result
        resultRank.textContent = resultData.rank;
        resultTitle.textContent = resultData.title;
        resultMessage.textContent = resultData.message;

        // Ensure CTA link is set (placeholder to be replaced by user)
        // affiliateLink.href = "YOUR_AFFILIATE_LINK_HERE"; 

        switchScreen('result');
    }
});
