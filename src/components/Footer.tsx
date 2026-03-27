import Link from "next/link";

const navLinks = [
  { href: "/", label: "Home" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/services", label: "Services" },
  { href: "/about", label: "About" },
  { href: "/contact", label: "Contact" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
];

export default function Footer() {
  return (
    <footer className="bg-charcoal text-white">
      <div className="max-w-7xl mx-auto px-6 py-12">
        <div className="flex flex-col md:flex-row items-center justify-between gap-8">
          {/* Left: Copyright */}
          <p className="text-sm text-gray-400">
            &copy; 2026 DomainSnobs LLC. All rights reserved.
          </p>

          {/* Center: Nav Links */}
          <nav className="flex flex-wrap justify-center gap-x-6 gap-y-2">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-sm text-gray-400 hover:text-white transition-colors"
              >
                {link.label}
              </Link>
            ))}
          </nav>

          {/* Right: Email */}
          <a
            href="mailto:acquisitions@domainsnobs.com"
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            acquisitions@domainsnobs.com
          </a>
        </div>

        {/* Bottom line */}
        <div className="mt-8 pt-6 border-t border-gray-700 text-center">
          <p className="text-xs text-gray-500">Atlanta, GA</p>
        </div>
      </div>
    </footer>
  );
}
