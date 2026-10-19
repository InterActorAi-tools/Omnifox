// Page title for the main tool. The logo already sits in the navbar, so
// this stays compact and the upload card is visible without scrolling.
const Hero = () => (
  <header className="w-full max-w-4xl text-center pt-8">
    <h1 className="text-3xl sm:text-4xl font-bold text-gray-900">Analyze comments</h1>
    <p className="mt-2 text-base sm:text-lg text-gray-600">
      Upload an Excel file or paste a post link. OmniCat translates every comment to English and sorts it by sentiment.
    </p>
  </header>
);

export default Hero;
