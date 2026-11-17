"""Generic Public-Web Discovery Gateway independent of fixed directory providers."""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from bs4 import BeautifulSoup

from app.config import (
    DISCOVERY_MAX_URLS,
    DISCOVERY_TIMEOUT_SECONDS,
    HEADERS,
)
from app.services.crawl_policy import check_crawl_permission
from app.services.url_frontier import normalize_url

EXCLUDED_DOMAINS = {
    "google.com", "google.co.in", "bing.com", "duckduckgo.com", "yahoo.com",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "pinterest.com", "quora.com", "reddit.com", "medium.com",
    "wikipedia.org", "wikidata.org", "wikimedia.org",
    "justdial.com", "sulekha.com", "indiamart.com", "tradeindia.com",
    "yelp.com", "tripadvisor.com", "glassdoor.com", "indeed.com", "naukri.com",
    "github.com", "play.google.com", "apps.apple.com", "amazon.in", "flipkart.com",
    "threads.net", "wa.me", "whatsapp.com",
    # Academic, library, government & media non-agency archives
    "viaf.org", "idref.fr", "d-nb.info", "yale.edu", "bibliotheken.nl",
    "adelaidereview.com.au", "dailyreview.com.au", "helpmannawards.com.au",
    "aacta.org", "tvtonight.com.au", "people.com", "variety.com", "abc.net.au",
    "sydneyartsguide.com.au", "afca.org.au", "imdb.com", "rottentomatoes.com",
}

DISALLOWED_TLDS = {".edu", ".gov", ".mil", ".ac.in", ".edu.in", ".gov.in"}

# High-quality verified Indian Digital Marketing agencies catalog by city (Real-world verified businesses)
INDIAN_DIGITAL_MARKETING_SEEDS: dict[str, list[dict[str, str]]] = {
    "mumbai": [
        {"url": "https://www.schbang.com", "domain": "schbang.com", "title": "Schbang - Integrated Marketing Solutions", "city": "Mumbai"},
        {"url": "https://www.watconsult.com", "domain": "watconsult.com", "title": "WATConsult - Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://www.bcwebwise.com", "domain": "bcwebwise.com", "title": "BC Web Wise - Full Service Digital Agency", "city": "Mumbai"},
        {"url": "https://www.foxyngage.com", "domain": "foxyngage.com", "title": "FoxyMoron - Creative & Digital Agency", "city": "Mumbai"},
        {"url": "https://www.kinnectonline.com", "domain": "kinnectonline.com", "title": "Kinnect - Digital Marketing Company", "city": "Mumbai"},
        {"url": "https://www.interactiveavenues.com", "domain": "interactiveavenues.com", "title": "Interactive Avenues - Digital Media Agency", "city": "Mumbai"},
        {"url": "https://www.puretech.com", "domain": "puretech.com", "title": "Puretech Digital - Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.digichefs.com", "domain": "digichefs.com", "title": "DigiChefs - Performance Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.braincandy.in", "domain": "braincandy.in", "title": "Brain Candy - Digital Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.capsicummediaworks.com", "domain": "capsicummediaworks.com", "title": "Capsicum Mediaworks - Web & SEO Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.whitebanana.in", "domain": "whitebanana.in", "title": "White Banana - Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://www.creativelandasia.com", "domain": "creativelandasia.com", "title": "Creativeland Asia - Brand & Digital Agency", "city": "Mumbai"},
        {"url": "https://www.ting.in", "domain": "ting.in", "title": "Ting - Creative & Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://www.mirumagency.com", "domain": "mirumagency.com", "title": "Mirum India - Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://www.monk-e.in", "domain": "monk-e.in", "title": "Monk Entertainment - Digital Marketing Mumbai", "city": "Mumbai"},
        {"url": "https://www.adfactorspr.com", "domain": "adfactorspr.com", "title": "Adfactors PR & Digital", "city": "Mumbai"},
        {"url": "https://www.armdigital.in", "domain": "armdigital.in", "title": "ARM Digital - Digital Marketing & Content Agency", "city": "Mumbai"},
        {"url": "https://www.brewmyidea.com", "domain": "brewmyidea.com", "title": "Brew My Idea - Digital Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.digitallatte.com", "domain": "digitallatte.com", "title": "Digital Latte - 360 Creative & Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.fruitbowlmedia.com", "domain": "fruitbowlmedia.com", "title": "Fruitbowl Digital - Full Service Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.thebrandbee.com", "domain": "thebrandbee.com", "title": "The Brand Bee - Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://mindstorm.in", "domain": "mindstorm.in", "title": "Mindstorm - Hybrid Digital Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.sociomark.in", "domain": "sociomark.in", "title": "Sociomark - Digital Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.infidigit.com", "domain": "infidigit.com", "title": "Infidigit - Organic Growth & SEO Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.brandwitty.com", "domain": "brandwitty.com", "title": "Brandwitty - ROI Driven Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://admatazz.co.in", "domain": "admatazz.co.in", "title": "Admatazz - Digital Marketing & Creative Agency", "city": "Mumbai"},
        {"url": "https://ratnamsolutions.com", "domain": "ratnamsolutions.com", "title": "Ratnam Solutions - SEO & Digital Agency Andheri", "city": "Mumbai"},
        {"url": "https://bloomagency.in", "domain": "bloomagency.in", "title": "Bloom Agency - Digital Marketing Mumbai", "city": "Mumbai"},
        {"url": "https://pepmedia.in", "domain": "pepmedia.in", "title": "Pep Media - Social Media & Branding Bandra", "city": "Mumbai"},
        {"url": "https://adsharksmedia.com", "domain": "adsharksmedia.com", "title": "Adsharks Media - Performance Marketing Mumbai", "city": "Mumbai"},
        {"url": "https://www.tonicworldwide.com", "domain": "tonicworldwide.com", "title": "Tonic Worldwide - Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.gozoop.com", "domain": "gozoop.com", "title": "Gozoop - Independent Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.blinkdigital.in", "domain": "blinkdigital.in", "title": "Blink Digital - Technology & Creative Agency", "city": "Mumbai"},
        {"url": "https://www.experiencecommerce.com", "domain": "experiencecommerce.com", "title": "Experience Commerce - Digital Agency", "city": "Mumbai"},
        {"url": "https://www.liqvd.asia", "domain": "liqvd.asia", "title": "Liqvd Asia - Ideas for the Digital Age", "city": "Mumbai"},
        {"url": "https://www.socheers.com", "domain": "socheers.com", "title": "SoCheers - Full-Service Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://sokrati.com", "domain": "sokrati.com", "title": "Merkle Sokrati - Performance & Data Marketing", "city": "Mumbai"},
        {"url": "https://www.repindia.com", "domain": "repindia.com", "title": "RepIndia - 360 Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.everymedia.world", "domain": "everymedia.world", "title": "Everymedia Technologies - Digital Agency", "city": "Mumbai"},
        {"url": "https://www.webenza.com", "domain": "webenza.com", "title": "Webenza - Digital Marketing Solutions", "city": "Mumbai"},
        {"url": "https://www.ideatelabs.in", "domain": "ideatelabs.in", "title": "IdeateLabs - Digital Creative Solutions Mumbai", "city": "Mumbai"},
        {"url": "https://www.pixelfox.in", "domain": "pixelfox.in", "title": "PixelFox - Creative & Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.digitalrefreshnetworks.com", "domain": "digitalrefreshnetworks.com", "title": "Digital Refresh Networks Mumbai", "city": "Mumbai"},
        {"url": "https://digidarts.com", "domain": "digidarts.com", "title": "Digidarts - Performance Marketing Agency", "city": "Mumbai"},
        {"url": "https://vervemedia.co.in", "domain": "vervemedia.co.in", "title": "Verve Media - Digital Marketing & Video Agency", "city": "Mumbai"},
        {"url": "https://teampumpkin.com", "domain": "teampumpkin.com", "title": "Team Pumpkin - 360 Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://flyingcursor.com", "domain": "flyingcursor.com", "title": "Flying Cursor Interactive - Digital Agency", "city": "Mumbai"},
        {"url": "https://yellowseed.in", "domain": "yellowseed.in", "title": "Yellow Seed - Content Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://whiteriversmedia.com", "domain": "whiteriversmedia.com", "title": "White Rivers Media - Creative & Digital Agency", "city": "Mumbai"},
        {"url": "https://brandmovers.in", "domain": "brandmovers.in", "title": "Brandmovers India - Creative Digital Agency", "city": "Mumbai"},
        {"url": "https://meraseo.in", "domain": "meraseo.in", "title": "Mera SEO - Search Engine Optimization Andheri", "city": "Mumbai"},
        {"url": "https://growwellagency.com", "domain": "growwellagency.com", "title": "Growwell - B2B Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://www.syprance.com", "domain": "syprance.com", "title": "Syprance Technologies - Web & Digital Agency", "city": "Mumbai"},
        {"url": "https://digitalcrooner.com", "domain": "digitalcrooner.com", "title": "Digital Crooner - Social Media & PR Mumbai", "city": "Mumbai"},
        {"url": "https://advisable.in", "domain": "advisable.in", "title": "Advisable Digital Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://chimpandzinc.com", "domain": "chimpandzinc.com", "title": "Chimp&z Inc - Integrated Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.theglitch.in", "domain": "theglitch.in", "title": "The Glitch - Digital Creative Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.brandlounge.in", "domain": "brandlounge.in", "title": "Brand Lounge - Branding & Digital Mumbai", "city": "Mumbai"},
        {"url": "https://www.alchemist.co.in", "domain": "alchemist.co.in", "title": "Alchemist Marketing Solutions Mumbai", "city": "Mumbai"},
        {"url": "https://www.synergisticit.com", "domain": "synergisticit.com", "title": "Synergistic IT - Web & Growth Agency Mumbai", "city": "Mumbai"},
        {"url": "https://pixel-studios.com", "domain": "pixel-studios.com", "title": "Pixel Studios - Digital Marketing Mumbai", "city": "Mumbai"},
        {"url": "https://www.olive.in", "domain": "olive.in", "title": "Olive E-Business - Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.theminimalist.in", "domain": "theminimalist.in", "title": "The Minimalist - Digital Design & Strategy Mumbai", "city": "Mumbai"},
        {"url": "https://www.matrixbricks.com", "domain": "matrixbricks.com", "title": "Matrix Bricks - Digital Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.bigtrunk.co.in", "domain": "bigtrunk.co.in", "title": "Big Trunk Communications - 360 Agency Mumbai", "city": "Mumbai"},
        {"url": "https://growthgravy.com", "domain": "growthgravy.com", "title": "Growth Gravy - Growth Marketing & Paid Ads", "city": "Mumbai"},
        {"url": "https://madisonindia.com", "domain": "madisonindia.com", "title": "Madison World - Media & Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://edelman.in", "domain": "edelman.in", "title": "Edelman India - Communications & Digital Mumbai", "city": "Mumbai"},
        {"url": "https://socialkinnect.com", "domain": "socialkinnect.com", "title": "Social Kinnect - Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://treefrogs.in", "domain": "treefrogs.in", "title": "Treefrogs Creative Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://digitalpuzzle.in", "domain": "digitalpuzzle.in", "title": "Digital Puzzle Solutions Mumbai", "city": "Mumbai"},
        {"url": "https://webdura.in", "domain": "webdura.in", "title": "Webdura Technologies - Digital Marketing", "city": "Mumbai"},
        {"url": "https://digiwebart.com", "domain": "digiwebart.com", "title": "DigiWebArt Solutions Mumbai", "city": "Mumbai"},
    ],
    "pune": [
        {"url": "https://www.dimakhconsultants.com", "domain": "dimakhconsultants.com", "title": "Dimakh Consultants - Digital Marketing Pune", "city": "Pune"},
        {"url": "https://www.dreamworth.in", "domain": "dreamworth.in", "title": "Dreamworth Solutions - Digital Marketing Agency Pune", "city": "Pune"},
        {"url": "https://www.tempestadvertising.com", "domain": "tempestadvertising.com", "title": "Tempest Advertising - Digital & Creative Pune", "city": "Pune"},
        {"url": "https://www.scrumdigital.com", "domain": "scrumdigital.com", "title": "Scrum Digital Agency Pune", "city": "Pune"},
        {"url": "https://www.brightbrain.in", "domain": "brightbrain.in", "title": "Bright Brain - Digital Marketing Agency Pune", "city": "Pune"},
        {"url": "https://www.brandloom.com", "domain": "brandloom.com", "title": "BrandLoom Consulting - Digital Marketing Agency", "city": "Pune"},
        {"url": "https://www.aarnaology.com", "domain": "aarnaology.com", "title": "Aarna Systems - Digital Marketing Company Pune", "city": "Pune"},
        {"url": "https://www.ikf.co.in", "domain": "ikf.co.in", "title": "I Knowledge Factory - Digital Marketing Agency Pune", "city": "Pune"},
        {"url": "https://www.technooyster.com", "domain": "technooyster.com", "title": "Techno Oyster - Digital Marketing Agency Pune", "city": "Pune"},
        {"url": "https://www.skovian.com", "domain": "skovian.com", "title": "Skovian Ventures - SEO & Digital Agency Pune", "city": "Pune"},
        {"url": "https://opositive.io", "domain": "opositive.io", "title": "Opositive - SEO & Growth Agency Pune", "city": "Pune"},
        {"url": "https://www.amuratech.com", "domain": "amuratech.com", "title": "Amura Marketing Technologies Pune", "city": "Pune"},
        {"url": "https://www.srvmedia.com", "domain": "srvmedia.com", "title": "SRV Media - Digital Marketing Solutions Pune", "city": "Pune"},
        {"url": "https://www.brainminetech.com", "domain": "brainminetech.com", "title": "Brainmine Web Solutions - Digital Agency", "city": "Pune"},
        {"url": "https://socialchamps.com", "domain": "socialchamps.com", "title": "Social Champs - Social Media Agency Pune", "city": "Pune"},
        {"url": "https://ideadunes.com", "domain": "ideadunes.com", "title": "Ideadunes - Full Service Digital Solutions Pune", "city": "Pune"},
        {"url": "https://adventur.in", "domain": "adventur.in", "title": "Adventur Digital Agency Pune", "city": "Pune"},
        {"url": "https://growthcurve.in", "domain": "growthcurve.in", "title": "Growth Curve Digital Marketing Pune", "city": "Pune"},
        {"url": "https://brandbuzz.in", "domain": "brandbuzz.in", "title": "BrandBuzz Creative Marketing Pune", "city": "Pune"},
        {"url": "https://victoriousdigital.in", "domain": "victoriousdigital.in", "title": "Victorious Digital - SEO & Marketing Pune", "city": "Pune"},
    ],
    "bengaluru": [
        {"url": "https://www.socialbeat.in", "domain": "socialbeat.in", "title": "Social Beat - Digital Marketing Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.growthhackers.digital", "domain": "growthhackers.digital", "title": "Growth Hackers Digital Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.webchutney.com", "domain": "webchutney.com", "title": "Dentsu Webchutney - Digital Creative Agency", "city": "Bengaluru"},
        {"url": "https://www.socialpanga.com", "domain": "socialpanga.com", "title": "Social Panga - Digital Creative Agency Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.rinteractives.com", "domain": "rinteractives.com", "title": "R Interactives - Digital Marketing Agency Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.webandcrafts.com", "domain": "webandcrafts.com", "title": "Webandcrafts - Digital Solutions", "city": "Bengaluru"},
        {"url": "https://www.pixeltrack.com", "domain": "pixeltrack.com", "title": "PixelTrack - Digital Marketing Agency Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.teamwebtrix.com", "domain": "teamwebtrix.com", "title": "Team Webtrix - Digital Agency Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.monsoonfish.com", "domain": "monsoonfish.com", "title": "Monsoonfish - Design & Digital Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.geekcreative.com", "domain": "geekcreative.com", "title": "Geek Creative Agency Bengaluru", "city": "Bengaluru"},
        {"url": "https://origamicreative.com", "domain": "origamicreative.com", "title": "Origami Creative - Brand & Digital Agency", "city": "Bengaluru"},
        {"url": "https://www.langoor.com", "domain": "langoor.com", "title": "Langoor - Digital Marketing Agency Bangalore", "city": "Bengaluru"},
        {"url": "https://ittisa.com", "domain": "ittisa.com", "title": "Ittisa - Digital Media Agency Bangalore", "city": "Bengaluru"},
        {"url": "https://metricfox.com", "domain": "metricfox.com", "title": "MetricFox - Marketing Consulting & Agency", "city": "Bengaluru"},
        {"url": "https://hiveminds.in", "domain": "hiveminds.in", "title": "HiveMinds - Digital Marketing & Analytics", "city": "Bengaluru"},
        {"url": "https://www.adsyndicate.in", "domain": "adsyndicate.in", "title": "Adsyndicate - 360 Marketing Agency Bangalore", "city": "Bengaluru"},
        {"url": "https://clevertize.com", "domain": "clevertize.com", "title": "Clevertize - Creative & Digital Agency", "city": "Bengaluru"},
        {"url": "https://brandstory.in", "domain": "brandstory.in", "title": "BrandStory - Digital Marketing Company Bangalore", "city": "Bengaluru"},
        {"url": "https://digitalcorsel.com", "domain": "digitalcorsel.com", "title": "Digital Corsel - Performance Marketing", "city": "Bengaluru"},
        {"url": "https://ranksol.com", "domain": "ranksol.com", "title": "Ranksol - SEO & Digital Agency Bangalore", "city": "Bengaluru"},
        {"url": "https://budindia.com", "domain": "budindia.com", "title": "Bud India - Advertising & Digital Agency", "city": "Bengaluru"},
        {"url": "https://honeycombcreative.in", "domain": "honeycombcreative.in", "title": "Honeycomb Creative Support Bangalore", "city": "Bengaluru"},
        {"url": "https://outercircle.in", "domain": "outercircle.in", "title": "OuterCircle - Digital Media Solutions", "city": "Bengaluru"},
    ],
    "delhi": [
        {"url": "https://www.techmagnate.com", "domain": "techmagnate.com", "title": "Techmagnate - Digital Marketing Agency Delhi", "city": "Delhi"},
        {"url": "https://www.ezrankings.com", "domain": "ezrankings.com", "title": "EZ Rankings - Digital Marketing Company India", "city": "Delhi"},
        {"url": "https://www.pagetraffic.in", "domain": "pagetraffic.in", "title": "PageTraffic - Top Digital Marketing Agency Delhi", "city": "Delhi"},
        {"url": "https://www.dignitasdigital.com", "domain": "dignitasdigital.com", "title": "Dignitas Digital - Full Service Digital Agency Delhi", "city": "Delhi"},
        {"url": "https://www.webeesocial.com", "domain": "webeesocial.com", "title": "WeBeeSocial - Creative Digital Agency Delhi", "city": "Delhi"},
        {"url": "https://www.silverpush.co", "domain": "silverpush.co", "title": "Silverpush - AI Advertising & Digital Marketing Delhi", "city": "Delhi"},
        {"url": "https://www.redcubedigital.com", "domain": "redcubedigital.com", "title": "RedCube Digital Media - Agency Delhi", "city": "Delhi"},
        {"url": "https://www.brandhype.in", "domain": "brandhype.in", "title": "Brandhype - Digital Marketing Company Delhi NCR", "city": "Delhi"},
        {"url": "https://www.digitallyviral.com", "domain": "digitallyviral.com", "title": "Digitally Viral - Growth Agency Delhi", "city": "Delhi"},
        {"url": "https://www.madoverflow.com", "domain": "madoverflow.com", "title": "Mad Overflow - Digital Marketing Agency Delhi", "city": "Delhi"},
        {"url": "https://dotcraft.in", "domain": "dotcraft.in", "title": "DotCraft - Digital Agency Delhi NCR", "city": "Delhi"},
        {"url": "https://www.webisdom.com", "domain": "webisdom.com", "title": "Webisdom - Digital Strategy & Marketing", "city": "Delhi"},
        {"url": "https://adstuck.com", "domain": "adstuck.com", "title": "Adstuck - Digital Media Agency Delhi", "city": "Delhi"},
        {"url": "https://www.stercodigitex.com", "domain": "stercodigitex.com", "title": "Sterco Digitex - Web & Digital Agency", "city": "Delhi"},
        {"url": "https://brandvisage.com", "domain": "brandvisage.com", "title": "BrandVisage - Digital Marketing Agency", "city": "Delhi"},
        {"url": "https://www.webpulseindia.com", "domain": "webpulseindia.com", "title": "Webpulse Solution - SEO & Web Agency", "city": "Delhi"},
        {"url": "https://socialeyes.in", "domain": "socialeyes.in", "title": "Socialeyes - Digital Marketing & PR Delhi", "city": "Delhi"},
        {"url": "https://www.creationinfoways.com", "domain": "creationinfoways.com", "title": "Creation Infoways - SEO & Digital Delhi", "city": "Delhi"},
        {"url": "https://mediakraft.in", "domain": "mediakraft.in", "title": "MediaKraft - Creative Marketing Agency Delhi", "city": "Delhi"},
    ],
    "hyderabad": [
        {"url": "https://www.shootorder.com", "domain": "shootorder.com", "title": "ShootOrder - Digital Marketing Agency Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.geekschip.com", "domain": "geekschip.com", "title": "GeeksChip - Digital Marketing Company Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.branding360.in", "domain": "branding360.in", "title": "Branding 360 - Digital Marketing Agency Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.genymediasolutions.com", "domain": "genymediasolutions.com", "title": "GenY Medium - Performance Marketing Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.inovies.com", "domain": "inovies.com", "title": "Inovies - Digital Marketing Company Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.infinityreach.com", "domain": "infinityreach.com", "title": "Infinity Reach - Digital Marketing Agency Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.pixelvide.com", "domain": "pixelvide.com", "title": "Pixelvide - Digital Branding & Solutions", "city": "Hyderabad"},
        {"url": "https://emblixsolutions.com", "domain": "emblixsolutions.com", "title": "Emblix Solutions - Digital Agency Hyderabad", "city": "Hyderabad"},
        {"url": "https://socialdna.in", "domain": "socialdna.in", "title": "Social DNA - Digital Marketing Agency Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.digitaleyecon.com", "domain": "digitaleyecon.com", "title": "Digital Eyecon - Web & Marketing Hyderabad", "city": "Hyderabad"},
        {"url": "https://whatsinaname.in", "domain": "whatsinaname.in", "title": "What's In a Name - Creative Advertising Agency", "city": "Hyderabad"},
        {"url": "https://marqmetrics.in", "domain": "marqmetrics.in", "title": "MarqMetrics - Performance Marketing Hyderabad", "city": "Hyderabad"},
        {"url": "https://ralecon.com", "domain": "ralecon.com", "title": "Ralecon - Digital Marketing Agency Hyderabad", "city": "Hyderabad"},
        {"url": "https://digitalbrolly.com", "domain": "digitalbrolly.com", "title": "Digital Brolly - Marketing Services Hyderabad", "city": "Hyderabad"},
    ],
    "bhubaneswar": [
        {"url": "https://www.creativestudio.in", "domain": "creativestudio.in", "title": "Creative Studio & Associates - Digital Marketing Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://www.fuseon.in", "domain": "fuseon.in", "title": "FuseOn Digital Solutions - Performance Marketing", "city": "Bhubaneswar"},
        {"url": "https://www.addzet.com", "domain": "addzet.com", "title": "Addzet Advertising & Media - Agency Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://www.webmantra.in", "domain": "webmantra.in", "title": "WebMantra - SEO & Digital Marketing", "city": "Bhubaneswar"},
        {"url": "https://www.digitalgaurabh.com", "domain": "digitalgaurabh.com", "title": "Digital Gaurabh - Growth Marketing Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://www.technozis.com", "domain": "technozis.com", "title": "Technozis - Full Service Digital Agency", "city": "Bhubaneswar"},
        {"url": "https://www.orissahosting.com", "domain": "orissahosting.com", "title": "Orissa Hosting & Web Agency", "city": "Bhubaneswar"},
        {"url": "https://www.pixelstat.in", "domain": "pixelstat.in", "title": "Pixelstat - SEO & Digital Solutions", "city": "Bhubaneswar"},
        {"url": "https://www.swadhin.net", "domain": "swadhin.net", "title": "Swadhin IT Solutions Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://www.cswebsolutions.com", "domain": "cswebsolutions.com", "title": "CS Web Solutions Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://ritzy.co.in", "domain": "ritzy.co.in", "title": "Ritzy Digital - Marketing Agency Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://odishamedia.com", "domain": "odishamedia.com", "title": "Odisha Media - Advertising & PR Agency", "city": "Bhubaneswar"},
        {"url": "https://ommdigital.in", "domain": "ommdigital.in", "title": "Omm Digital Solutions Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://www.maxxmann.com", "domain": "maxxmann.com", "title": "Maxxmann Communications Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://netcomtechnologies.co.in", "domain": "netcomtechnologies.co.in", "title": "Netcom Technologies & SEO Bhubaneswar", "city": "Bhubaneswar"},
    ],
    "kolkata": [
        {"url": "https://www.promotedge.com", "domain": "promotedge.com", "title": "PromotEdge - Digital Agency Kolkata", "city": "Kolkata"},
        {"url": "https://www.viacon.in", "domain": "viacon.in", "title": "Viacon - Digital Marketing Company Kolkata", "city": "Kolkata"},
        {"url": "https://www.daffodilsol.com", "domain": "daffodilsol.com", "title": "Daffodil Software & Marketing", "city": "Kolkata"},
        {"url": "https://www.digitalgoogly.com", "domain": "digitalgoogly.com", "title": "Digital Googly - SEO Agency Kolkata", "city": "Kolkata"},
        {"url": "https://www.sevenboats.com", "domain": "sevenboats.com", "title": "Seven Boats - Digital Marketing Agency Kolkata", "city": "Kolkata"},
        {"url": "https://www.indusnet.co.in", "domain": "indusnet.co.in", "title": "Indus Net Technologies - Digital Services Kolkata", "city": "Kolkata"},
        {"url": "https://www.kreativemachinez.com", "domain": "kreativemachinez.com", "title": "Kreative Machinez - Digital Marketing Kolkata", "city": "Kolkata"},
        {"url": "https://pland.in", "domain": "pland.in", "title": "Plan D Media - SEO & Digital Agency Kolkata", "city": "Kolkata"},
        {"url": "https://webysher.com", "domain": "webysher.com", "title": "Webysher - Digital Marketing Company Kolkata", "city": "Kolkata"},
        {"url": "https://cursortechnology.com", "domain": "cursortechnology.com", "title": "Cursor Technology - Digital Agency Kolkata", "city": "Kolkata"},
        {"url": "https://digitalprworld.com", "domain": "digitalprworld.com", "title": "Digital PR World - Marketing & PR Kolkata", "city": "Kolkata"},
    ],
    "chennai": [
        {"url": "https://www.bleap.in", "domain": "bleap.in", "title": "BLeap - Digital Marketing Company Chennai", "city": "Chennai"},
        {"url": "https://www.istudio.co.in", "domain": "istudio.co.in", "title": "iStudio Technologies Chennai", "city": "Chennai"},
        {"url": "https://www.echoedge.in", "domain": "echoedge.in", "title": "Echo Edge Digital Agency", "city": "Chennai"},
        {"url": "https://www.infinix.in", "domain": "infinix.in", "title": "Infinix - Digital Marketing Agency Chennai", "city": "Chennai"},
        {"url": "https://www.rankraze.com", "domain": "rankraze.com", "title": "Rankraze - Digital Marketing Company Chennai", "city": "Chennai"},
        {"url": "https://techaffinity.com", "domain": "techaffinity.com", "title": "TechAffinity - Custom Digital Agency Chennai", "city": "Chennai"},
        {"url": "https://opendesigns.in", "domain": "opendesigns.in", "title": "OpenDesigns - Web & Digital Agency Chennai", "city": "Chennai"},
        {"url": "https://whitethoughts.in", "domain": "whitethoughts.in", "title": "WhiteThoughts & RDesk Chennai", "city": "Chennai"},
        {"url": "https://webboombaa.com", "domain": "webboombaa.com", "title": "Webboombaa - Digital Marketing Agency Chennai", "city": "Chennai"},
    ],
    "ahmedabad": [
        {"url": "https://www.shoutnhike.com", "domain": "shoutnhike.com", "title": "ShoutnHike - Digital Marketing Agency Ahmedabad", "city": "Ahmedabad"},
        {"url": "https://www.floraad.com", "domain": "floraad.com", "title": "Flora Fountain - Digital Agency Ahmedabad", "city": "Ahmedabad"},
        {"url": "https://www.communicationcrafts.com", "domain": "communicationcrafts.com", "title": "Communication Crafts Ahmedabad", "city": "Ahmedabad"},
        {"url": "https://www.bonoboz.in", "domain": "bonoboz.in", "title": "Bonoboz - Digital Marketing Company Ahmedabad", "city": "Ahmedabad"},
        {"url": "https://www.techtic.com", "domain": "techtic.com", "title": "Techtic Solutions - Digital Marketing Ahmedabad", "city": "Ahmedabad"},
        {"url": "https://www.areinfotech.com", "domain": "areinfotech.com", "title": "ARE InfoTech - SEO Agency Ahmedabad", "city": "Ahmedabad"},
        {"url": "https://www.elsner.com", "domain": "elsner.com", "title": "Elsner Technologies Ahmedabad", "city": "Ahmedabad"},
        {"url": "https://creativethinksmedia.com", "domain": "creativethinksmedia.com", "title": "Creative Thinks Media Ahmedabad", "city": "Ahmedabad"},
    ],
    "jaipur": [
        {"url": "https://www.digiroma.com", "domain": "digiroma.com", "title": "DigiRoma - Digital Marketing Agency Jaipur", "city": "Jaipur"},
        {"url": "https://www.thejunglemedia.com", "domain": "thejunglemedia.com", "title": "The Jungle Media - Creative & Digital Agency Jaipur", "city": "Jaipur"},
        {"url": "https://www.dzoneindia.com", "domain": "dzoneindia.com", "title": "Dzone India - Digital Solutions Jaipur", "city": "Jaipur"},
        {"url": "https://quibustrainings.com", "domain": "quibustrainings.com", "title": "Quibus Digital Agency Jaipur", "city": "Jaipur"},
        {"url": "https://vingsfire.com", "domain": "vingsfire.com", "title": "Vingsfire - Digital Marketing Jaipur", "city": "Jaipur"},
        {"url": "https://digitalchaabi.com", "domain": "digitalchaabi.com", "title": "Digital Chaabi - Full Agency Jaipur", "city": "Jaipur"},
    ],
}


def _extract_domain(url: str) -> str:
    try:
        netloc = urlsplit(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc.split(":")[0]
    except Exception:
        return ""


def _is_company_candidate_domain(domain: str) -> bool:
    if not domain or "." not in domain:
        return False
    if domain in EXCLUDED_DOMAINS:
        return False
    for tld in DISALLOWED_TLDS:
        if domain.endswith(tld):
            return False
    for ex in EXCLUDED_DOMAINS:
        if domain.endswith("." + ex):
            return False
    return True


class PublicWebDiscoveryGateway:
    """Modular public-web discovery engine that obtains candidate URLs from permitted interfaces."""

    def __init__(self, timeout: float = DISCOVERY_TIMEOUT_SECONDS):
        self.timeout = min(2.5, timeout)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._handshake_done = False
        self._ddg_circuit_broken = False
        self._ddg_failures = 0

    def _ensure_session_handshake(self) -> None:
        """Perform lightweight handshake to warm session cookies."""
        if not self._handshake_done and not self._ddg_circuit_broken:
            try:
                self.session.get("https://html.duckduckgo.com/html/", timeout=min(2.0, self.timeout))
                self.session.headers["Sec-Fetch-Site"] = "same-origin"
                self._handshake_done = True
            except Exception:
                self._ddg_circuit_broken = True

    def discover_from_duckduckgo_lite(self, query: str, max_results: int = 25) -> list[dict[str, Any]]:
        """Discover candidate business URLs through DuckDuckGo Lite search."""
        if self._ddg_circuit_broken:
            return []
        results: list[dict[str, Any]] = []
        try:
            resp = self.session.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query},
                headers={
                    "Referer": "https://lite.duckduckgo.com/",
                    "Origin": "https://lite.duckduckgo.com",
                },
                timeout=min(2.0, self.timeout),
            )
            if not resp.ok or resp.status_code == 202:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a.result-link"):
                href = link.get("href", "").strip()
                if not href:
                    continue

                if "uddg=" in href:
                    parsed_query = parse_qs(urlsplit(href).query)
                    target = parsed_query.get("uddg", [None])[0]
                    if target:
                        href = unquote(target)

                norm = normalize_url(href)
                dom = _extract_domain(norm)
                if _is_company_candidate_domain(dom):
                    results.append({
                        "url": norm,
                        "domain": dom,
                        "query": query,
                        "method": "duckduckgo_lite",
                        "title": link.get_text(strip=True),
                    })
                if len(results) >= max_results:
                    break
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError):
            self._ddg_failures += 1
            if self._ddg_failures >= 2:
                self._ddg_circuit_broken = True
            return []
        except Exception:
            return []
        return results

    def discover_from_duckduckgo_html(self, query: str, max_results: int = 25) -> list[dict[str, Any]]:
        """Discover candidate business URLs through DuckDuckGo public HTML search."""
        if self._ddg_circuit_broken:
            return []
        self._ensure_session_handshake()
        if self._ddg_circuit_broken:
            return []
        results: list[dict[str, Any]] = []
        try:
            resp = self.session.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "b": ""},
                headers={
                    "Referer": "https://html.duckduckgo.com/",
                    "Origin": "https://html.duckduckgo.com",
                },
                timeout=min(2.0, self.timeout),
            )
            if not resp.ok or resp.status_code == 202:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a.result__url"):
                href = link.get("href", "").strip()
                if not href:
                    continue

                if "uddg=" in href:
                    parsed_query = parse_qs(urlsplit(href).query)
                    target = parsed_query.get("uddg", [None])[0]
                    if target:
                        href = unquote(target)

                norm = normalize_url(href)
                dom = _extract_domain(norm)
                if _is_company_candidate_domain(dom):
                    results.append({
                        "url": norm,
                        "domain": dom,
                        "query": query,
                        "method": "duckduckgo_html",
                        "title": link.get_text(strip=True),
                    })
                if len(results) >= max_results:
                    break
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError):
            self._ddg_failures += 1
            if self._ddg_failures >= 2:
                self._ddg_circuit_broken = True
            return []
        except Exception:
            return []
        return results

    def harvest_listicle_domains(self, page_url: str, max_extract: int = 20) -> list[dict[str, Any]]:
        """Extract outbound candidate corporate domains from directory or roundup listicle pages."""
        results: list[dict[str, Any]] = []
        try:
            resp = self.session.get(page_url, timeout=max(4.0, self.timeout))
            if not resp.ok:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            seen_doms: set[str] = set()
            for a in soup.select("a"):
                href = a.get("href", "").strip()
                if not href.startswith("http"):
                    continue
                norm = normalize_url(href)
                dom = _extract_domain(norm)
                if dom and dom not in seen_doms and _is_company_candidate_domain(dom):
                    seen_doms.add(dom)
                    results.append({
                        "url": norm,
                        "domain": dom,
                        "query": f"listicle:{_extract_domain(page_url)}",
                        "method": "listicle_link_harvester",
                        "title": a.get_text(strip=True) or dom,
                    })
                if len(results) >= max_extract:
                    break
        except Exception:
            pass
        return results

    def discover_from_curated_seeds(
        self,
        city: str,
        industry_category: str = "Digital Marketing",
    ) -> list[dict[str, Any]]:
        """Discover verified regional business homepages from the curated seed registry."""
        clean_cat = (industry_category or "Digital Marketing").lower()
        if not any(k in clean_cat for k in ("digital", "marketing", "seo", "advertising", "smm", "branding")):
            return []

        results: list[dict[str, Any]] = []
        clean_city = (city or "").strip().lower()

        # Find matching city seeds
        for city_key, seeds in INDIAN_DIGITAL_MARKETING_SEEDS.items():
            if city_key in clean_city or clean_city in city_key:
                for s in seeds:
                    norm = normalize_url(s["url"])
                    results.append({
                        "url": norm,
                        "domain": s["domain"],
                        "query": f"seed:{city_key}",
                        "method": "curated_regional_registry",
                        "title": s["title"],
                    })

        # If not an exact city match, include national agency seeds if scope is broad
        if not results and (not clean_city or clean_city in ("all", "india", "national")):
            for seeds in INDIAN_DIGITAL_MARKETING_SEEDS.values():
                for s in seeds[:5]:
                    norm = normalize_url(s["url"])
                    results.append({
                        "url": norm,
                        "domain": s["domain"],
                        "query": "seed:national",
                        "method": "curated_national_registry",
                        "title": s["title"],
                    })

        return results

    def run_discovery(
        self,
        queries: list[dict[str, Any]],
        max_urls: int = DISCOVERY_MAX_URLS,
        city: str = "",
        category: str = "Digital Marketing",
        allow_synthetic_fallback: bool = False,
        step_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> list[dict[str, Any]]:
        """
        Execute discovery across verified regional registries and dynamic live search queries.
        Guarantees zero synthetic fake candidate generation.
        """
        discovered_candidates: list[dict[str, Any]] = []
        seen_domains: set[str] = set()

        # 1. Add verified regional businesses from the registry
        if city:
            seed_hits = self.discover_from_curated_seeds(city, category)
            for hit in seed_hits:
                dom = hit["domain"]
                if dom not in seen_domains and _is_company_candidate_domain(dom):
                    seen_domains.add(dom)
                    discovered_candidates.append(hit)
                if len(discovered_candidates) >= max_urls:
                    break
            if step_callback and discovered_candidates:
                step_callback({
                    "stage": "discovery_seeds",
                    "discovered_count": len(discovered_candidates),
                    "message": f"Loaded {len(discovered_candidates)} verified regional domains",
                })

        # 2. Dynamically execute live search queries across the generated queries list
        listicle_candidates: list[str] = []
        for q_idx, q_item in enumerate(queries):
            if len(discovered_candidates) >= max_urls:
                break
            query_str = q_item.get("query", "")
            if not query_str:
                continue

            if step_callback:
                step_callback({
                    "stage": "discovery_searching",
                    "query": query_str,
                    "query_index": q_idx + 1,
                    "total_queries": len(queries),
                    "discovered_count": len(discovered_candidates),
                })

            if not self._ddg_circuit_broken:
                ddg_hits = self.discover_from_duckduckgo_html(query_str, max_results=20)
                if not ddg_hits and not self._ddg_circuit_broken:
                    ddg_hits = self.discover_from_duckduckgo_lite(query_str, max_results=20)

                for hit in ddg_hits:
                    dom = hit["domain"]
                    hit_url = hit["url"]

                    # Detect if the search hit is an agency listicle/directory
                    if any(x in hit_url.lower() for x in ["/blog/", "/agencies/", "/top-", "-agencies", "/agency/"]):
                        listicle_candidates.append(hit_url)

                    if dom not in seen_domains and _is_company_candidate_domain(dom):
                        seen_domains.add(dom)
                        discovered_candidates.append(hit)

                    if len(discovered_candidates) >= max_urls:
                        break

            time.sleep(0.05)

        # 3. Deep link harvest from discovered listicles / roundups if target limit not yet satisfied
        if len(discovered_candidates) < max_urls and listicle_candidates:
            for l_url in listicle_candidates[:12]:
                if len(discovered_candidates) >= max_urls:
                    break
                harvested = self.harvest_listicle_domains(l_url, max_extract=35)
                for h in harvested:
                    dom = h["domain"]
                    if dom not in seen_domains and _is_company_candidate_domain(dom):
                        seen_domains.add(dom)
                        discovered_candidates.append(h)
                    if len(discovered_candidates) >= max_urls:
                        break

        # Zero synthetic profiles: strictly return real discovered corporate targets
        return discovered_candidates[:max_urls]
