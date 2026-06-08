"""A small built-in job set so the UI is meaningful offline (no sources configured).

In production these come from ``ScoutAgent.run(...)``; here they are hand-written to
exercise both tracks, several countries, and a range of visa signals.
"""

from job_agent.models.candidate import Track
from job_agent.models.job import Job, VisaSignal


def demo_jobs() -> list[Job]:
    return [
        Job(source="personio", external_id="pa", title="Junior Public Affairs Officer",
            company="Rhône Public Affairs SA", country="CH", city="Geneva",
            visa_signal=VisaSignal.explicit_yes,
            url="https://rhone-public-affairs.jobs.personio.de/job/pa",
            description="Support advocacy and stakeholder engagement; policy analysis; draft reports."),
        Job(source="reliefweb", external_id="who", title="Junior Programme Officer",
            company="WHO", country="CH", city="Geneva", track=Track.intl_org,
            url="https://careers.who.int/careersection/ex/jobdetail.ftl?job=who",
            description="Coordinate global health programmes; monitoring and evaluation."),
        Job(source="greenhouse", external_id="dev", title="Backend Developer",
            company="Lac Léman Software SA", country="CH", city="Zürich",
            url="https://boards.greenhouse.io/lacleman/jobs/dev",
            description="Python, Kubernetes, distributed systems."),
        Job(source="personio", external_id="cz", title="Junior Data Analyst",
            company="Brno DataWorks", country="CZ", city="Brno",
            url="https://brno-dataworks.jobs.personio.de/job/cz",
            description="SQL, dashboards, reporting; policy research a plus."),
        Job(source="eures", external_id="nl", title="Junior Policy Consultant",
            company="Den Haag Advisory", country="NL", city="The Hague",
            visa_signal=VisaSignal.likely,
            url="https://ec.europa.eu/eures/portal/jv-se/jv-details/nl",
            description="International team; advocacy and stakeholder engagement."),
        Job(source="arbeitsagentur", external_id="de", title="EU Affairs Assistant",
            company="Berlin Institut", country="DE", city="Berlin",
            visa_signal=VisaSignal.explicit_no,
            url="https://www.arbeitsagentur.de/jobsuche/jobdetail/de",
            description="EU citizenship required. Policy analysis and research."),
    ]
