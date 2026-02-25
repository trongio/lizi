/**
 * Alpine.js Quiz Application Component
 *
 * Reads quiz data from window.QUIZ_REGISTRY and powers an interactive quiz UI.
 * Expects QUIZ_REGISTRY to be an array of test objects:
 * [
 *   {
 *     id: string,
 *     title: string,
 *     questions: [
 *       { id: number, text: string, options: string[], answer: number, explanation: string, image?: string }
 *     ]
 *   },
 *   ...
 * ]
 *
 * Shows a test selection screen when multiple tests are available.
 * Auto-selects if only one test exists.
 */

const GEORGIAN_LETTERS = ['\u10D0', '\u10D1', '\u10D2', '\u10D3', '\u10D4']; // ა, ბ, გ, დ, ე

function quizApp() {
  return {
    // --- State ---
    tests: [],            // all available tests from QUIZ_REGISTRY
    activeTest: null,     // currently selected test object (or null for selection screen)
    screen: 'select',     // 'select' | 'quiz'
    title: '',
    questions: [],
    answers: {},          // { [questionIndex]: { selected: number, isCorrect: boolean } }
    answered: 0,
    correct: 0,
    wrong: 0,

    // --- Lifecycle ---
    init() {
      const registry = window.QUIZ_REGISTRY;
      if (!Array.isArray(registry) || registry.length === 0) {
        console.error('quizApp: window.QUIZ_REGISTRY is missing or empty.');
        return;
      }
      this.tests = registry;

      // Auto-select if only one test exists
      if (this.tests.length === 1) {
        this.selectTest(this.tests[0].id);
      }
    },

    // --- Test selection ---
    selectTest(testId) {
      const test = this.tests.find(t => t.id === testId);
      if (!test) {
        console.error('quizApp: test not found for id:', testId);
        return;
      }
      this.activeTest = test;
      this.title = test.title || '';
      this.questions = test.questions || [];
      this.resetState();
      this.screen = 'quiz';
    },

    backToMenu() {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      setTimeout(() => {
        this.activeTest = null;
        this.title = '';
        this.questions = [];
        this.resetState();
        this.screen = 'select';
      }, 300);
    },

    // --- Computed helpers ---
    get totalQuestions() {
      return this.questions.length;
    },

    get progress() {
      if (this.totalQuestions === 0) return 0;
      return (this.answered / this.totalQuestions) * 100;
    },

    // --- Georgian letter for option index ---
    letter(optionIndex) {
      return GEORGIAN_LETTERS[optionIndex] || '';
    },

    // --- Core interaction ---
    selectAnswer(questionIndex, optionIndex) {
      // Prevent re-answering
      if (this.answers[questionIndex] !== undefined) return;

      const question = this.questions[questionIndex];
      const isCorrect = optionIndex === question.answer;

      this.answers[questionIndex] = {
        selected: optionIndex,
        isCorrect: isCorrect,
      };

      this.answered++;
      if (isCorrect) {
        this.correct++;
      } else {
        this.wrong++;
      }
    },

    // --- Question state queries ---
    isAnswered(questionIndex) {
      return this.answers[questionIndex] !== undefined;
    },

    wasCorrect(questionIndex) {
      const entry = this.answers[questionIndex];
      return entry ? entry.isCorrect : false;
    },

    wasWrong(questionIndex) {
      const entry = this.answers[questionIndex];
      return entry ? !entry.isCorrect : false;
    },

    // --- CSS class helpers ---

    /** Classes for the question card wrapper */
    cardClass(questionIndex) {
      if (!this.isAnswered(questionIndex)) return '';
      return this.wasCorrect(questionIndex) ? 'answered-correct' : 'answered-wrong';
    },

    /** Classes for an individual option button */
    optionClass(questionIndex, optionIndex) {
      const entry = this.answers[questionIndex];
      if (!entry) return '';

      const classes = ['disabled'];

      if (optionIndex === entry.selected) {
        // This is the option the user clicked
        classes.push(entry.isCorrect ? 'selected-correct' : 'selected-wrong');
      } else if (!entry.isCorrect && optionIndex === this.questions[questionIndex].answer) {
        // Wrong answer was chosen -- reveal the correct one
        classes.push('reveal-correct');
      }

      return classes.join(' ');
    },

    /** Classes for the explanation panel */
    explanationClass(questionIndex) {
      if (!this.isAnswered(questionIndex)) return '';
      return this.wasCorrect(questionIndex) ? 'explanation exp-correct' : 'explanation exp-wrong';
    },

    /** Icon for the explanation header */
    explanationIcon(questionIndex) {
      return this.wasCorrect(questionIndex) ? '\u2705' : '\uD83D\uDCA1'; // checkmark or lightbulb
    },

    // --- Animation delay for staggered card entrance ---
    cardDelay(questionIndex) {
      return `animation-delay: ${questionIndex * 0.03}s`;
    },

    // --- Reset ---
    resetState() {
      this.answers = {};
      this.answered = 0;
      this.correct = 0;
      this.wrong = 0;
    },

    reset() {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      setTimeout(() => {
        this.resetState();
      }, 300);
    },
  };
}
