import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Brain, Menu, X } from 'lucide-react';

// Landing-only navigation; the mobile disclosure stays in document flow.
export default function Navbar() {
  const [isOpen, setIsOpen] = useState(false);
  const toggleRef = useRef(null);
  function closeOnEscape(event) {
    if (event.key === 'Escape' && isOpen) {
      setIsOpen(false);
      toggleRef.current?.focus();
    }
  }
  function visitFeatures() {
    setIsOpen(false);
    document.getElementById('features')?.focus({ preventScroll: true });
  }
  return (
    <header className="lp-header" onKeyDown={closeOnEscape}>
      <nav className="lp-container lp-nav" aria-label="Main navigation">
        <Link to="/" className="lp-brand" aria-label="Interview-IQ home">
          <span className="lp-logo"><Brain size={21} aria-hidden="true" /></span>Interview-IQ
        </Link>
        <button ref={toggleRef} type="button" className="lp-menu-toggle"
          aria-label={isOpen ? 'Close navigation' : 'Open navigation'}
          aria-expanded={isOpen} aria-controls="landing-navigation" onClick={() => setIsOpen(!isOpen)}>
          {isOpen ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
        </button>
        <div id="landing-navigation" className={`lp-nav-links${isOpen ? ' is-open' : ''}`}>
          <a href="#features" onClick={visitFeatures}>Features</a>
          <Link to="/login" onClick={() => setIsOpen(false)}>Login</Link>
          <Link to="/register" className="lp-button lp-button-small" onClick={() => setIsOpen(false)}>
            Get Started <ArrowUpRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </nav>
    </header>
  );
}
