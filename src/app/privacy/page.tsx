import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy — DomainSnobs",
  description:
    "Privacy policy for DomainSnobs LLC, a domain investment and brokerage firm.",
};

export default function PrivacyPage() {
  return (
    <>
      {/* Hero */}
      <section className="bg-charcoal py-20">
        <div className="max-w-7xl mx-auto px-6 text-center">
          <h1 className="text-4xl md:text-5xl font-bold text-white tracking-tight">
            Privacy Policy
          </h1>
        </div>
      </section>

      {/* Content */}
      <section className="bg-surface py-16 md:py-24">
        <div className="max-w-3xl mx-auto px-6 prose-custom">
          <p className="text-muted text-sm mb-12">
            Effective date: January 1, 2025
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Information We Collect
          </h2>
          <p className="text-slate text-base leading-relaxed mb-4">
            DomainSnobs LLC collects information you provide directly when you
            contact us, submit an inquiry, or engage in a domain transaction.
            This may include your name, email address, company name, phone
            number, and details related to domain inquiries or purchases.
          </p>
          <p className="text-slate text-base leading-relaxed mb-10">
            We also collect standard web analytics data including IP address,
            browser type, referring pages, and pages visited. This data is
            collected through server logs and analytics services to understand
            how visitors interact with our website.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            How We Use Information
          </h2>
          <p className="text-slate text-base leading-relaxed mb-4">
            We use the information we collect to respond to inquiries, facilitate
            domain transactions, communicate regarding ongoing negotiations, and
            improve our services. We may also use contact information to send
            relevant updates about domains you have expressed interest in.
          </p>
          <p className="text-slate text-base leading-relaxed mb-10">
            Analytics data is used in aggregate to understand site usage
            patterns. We do not sell, rent, or share personal information with
            third parties for marketing purposes.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Data Sharing
          </h2>
          <p className="text-slate text-base leading-relaxed mb-10">
            We may share information with third-party service providers who
            assist in operating our business, including domain registrars, escrow
            services, payment processors, and email delivery providers. These
            parties are contractually obligated to handle your information in
            accordance with applicable privacy regulations. We may also disclose
            information when required by law or to protect our legal rights.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Cookies
          </h2>
          <p className="text-slate text-base leading-relaxed mb-10">
            Our website uses cookies and similar technologies to maintain session
            state, remember preferences, and collect analytics data. You may
            configure your browser to reject cookies, though this may affect
            certain site functionality. Third-party analytics providers may set
            their own cookies subject to their respective privacy policies.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Data Security
          </h2>
          <p className="text-slate text-base leading-relaxed mb-10">
            We implement reasonable administrative, technical, and physical
            safeguards to protect personal information against unauthorized
            access, alteration, disclosure, or destruction. All domain
            transaction communications are conducted over encrypted channels. No
            method of transmission over the internet is completely secure, and we
            cannot guarantee absolute security.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Contact
          </h2>
          <p className="text-slate text-base leading-relaxed">
            For questions regarding this privacy policy or to request deletion of
            your personal data, contact us at{" "}
            <a
              href="mailto:ben@domainsnobs.com"
              className="text-charcoal font-medium hover:text-gold transition-colors"
            >
              ben@domainsnobs.com
            </a>
            .
          </p>
        </div>
      </section>
    </>
  );
}
