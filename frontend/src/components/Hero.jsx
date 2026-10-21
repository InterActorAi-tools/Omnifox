import { wordmark } from '../assets';

// Page title for the main tool, with the wordmark centred above it.
const Hero = () => (
  <header className="w-full max-w-4xl text-center pt-8">
    <a href="/app" aria-label="OmniFox home" className="inline-block mb-4">
      <img src={wordmark} alt="" className="h-12 sm:h-16 w-auto object-contain" />
    </a>
    <h1 className="text-3xl sm:text-4xl font-bold text-gray-900">Analyze comments instantly!</h1>
    <p className="mt-2 text-base sm:text-lg text-gray-600">
      Upload an Excel file or paste a post link. OmniFox translates every comment to English and sorts it by sentiment.
    </p>
  </header>
);

export default Hero;
