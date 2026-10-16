# Email Authentication: SPF, DKIM and DMARC

Email authentication lets the receiving mail server check whether a message really comes from the domain in the From address. Three standards work together: SPF, DKIM and DMARC. Their results appear in the Authentication-Results header.

SPF (Sender Policy Framework) lists which mail servers are allowed to send email for a domain. The receiving server compares the sending server with that list. spf=pass means the server is allowed; spf=fail means it is not, which is a strong sign of spoofing.

DKIM (DomainKeys Identified Mail) adds a digital signature to each message. The receiving server checks the signature with a public key published by the sending domain. dkim=pass means the message was signed by that domain and was not changed in transit; dkim=none or dkim=fail means it could not be verified.

DMARC (Domain-based Message Authentication, Reporting and Conformance) tells receivers what to do when SPF and DKIM do not line up with the From domain: deliver, quarantine or reject. dmarc=fail means the visible sender domain could not be confirmed.

How to use these results: a fail on SPF, DKIM or DMARC is a red flag, especially combined with urgency or a link mismatch. A pass is not proof of safety, because attackers can register their own look-alike domains and pass all three checks. Always check the actual domain name too.

Authentication failures on a message that asks for credentials or payment are a strong warning sign that the sender is spoofed.
