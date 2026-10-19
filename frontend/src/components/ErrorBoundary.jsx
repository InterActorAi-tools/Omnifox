import { Component } from "react";

// Keeps a render error in one screen from blanking the whole app.
export default class ErrorBoundary extends Component {
    state = { hasError: false };

    static getDerivedStateFromError() {
        return { hasError: true };
    }

    render() {
        if (!this.state.hasError) return this.props.children;
        return (
            <div role="alert" className="min-h-screen flex flex-col items-center justify-center gap-4 p-6 text-center">
                <h1 className="text-2xl font-bold text-gray-900">Something went wrong</h1>
                <p className="text-gray-600">Please reload the page. If the problem continues, contact your administrator.</p>
                <button
                    onClick={() => window.location.reload()}
                    className="px-4 py-2 bg-[#2E7D38] hover:bg-[#256A2E] text-white rounded-lg font-medium">
                    Reload page
                </button>
            </div>
        );
    }
}
