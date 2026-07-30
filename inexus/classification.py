"""
App bundle-ID classification shared across knowledgeC.db, sms.db,
CallHistory.storedata, and interactionC.db loaders, so all four
artifact types use one consistent category/subcategory/confidence
taxonomy for the same underlying app.
"""

_MESSAGING_BUNDLES = {
    'com.apple.MobileSMS',
    'com.facebook.Messenger', 'net.whatsapp.WhatsApp', 'org.whispersystems.signal',
    'ph.telegra.Telegraph', 'com.tinyspeck.chatlyio', 'com.skype.skype',
    'com.microsoft.skype.teams', 'com.hammerandchisel.discord', 'com.kik.chat',
    'com.groupme.iphone-app', 'com.viber', 'jp.naver.line', 'com.wickr.pro.prod',
    'com.loki-project.loki-messenger', 'com.wearezeta.zclient.ios',
    'ch.threema.iapp', 'co.babypenguin.imo', 'ch.swisscows.messenger.teleguardapp',
    'com.adhoclabs.burner', 'us.zoom.videomeetings', 'com.silentcircle.SilentPhone',
    'com.google.Dynamite', 'com.google.GVDialer',
}
_SOCIAL_BUNDLES = {
    'com.burbn.instagram', 'com.atebits.Tweetie2', 'com.reddit.Reddit',
    'com.toyopagroup.picaboo', 'com.zhiliaoapp.musically', 'org.joinmastodon.app',
    'com.tmediatech.truthsocial', 'com.gettr.gettr', 'com.mewe',
}
_CLOUD_BUNDLES  = {'mega.ios', 'com.google.Drive', 'com.dropbox.Dropbox', 'com.box.Box'}
_EMAIL_BUNDLES  = {
    'com.google.Gmail', 'com.microsoft.Outlook', 'com.apple.mobilemail',
    'ch.protonmail.protonmail', 'de.tutao.tutanota',
}

# Apple's own first-party bundle IDs that show up constantly in usage data —
# kept separate from the third-party categories above so app-usage sessions
# can be labeled "Apple System App" rather than falling into "Unknown".
_APPLE_SYSTEM_BUNDLES = {
    'com.apple.mobilesafari', 'com.apple.camera', 'com.apple.mobileslideshow',
    'com.apple.MobileSMS', 'com.apple.mobilephone', 'com.apple.facetime',
    'com.apple.Preferences', 'com.apple.AppStore', 'com.apple.Maps',
    'com.apple.Music', 'com.apple.Health', 'com.apple.Fitness',
    'com.apple.mobilenotes', 'com.apple.mobilecal', 'com.apple.findmy',
    'com.apple.MobileAddressBook', 'com.apple.mobiletimer', 'com.apple.journal',
    'com.apple.DocumentsApp', 'com.apple.InCallService', 'com.apple.Bridge',
}


def categorize_bundle_id(bundle, display=None):
    """
    Shared bundle-ID → (category, subcategory) categorizer used by both
    classify_asset_source() (Photos.sqlite import provenance) and
    classify_app_session() (knowledgeC.db /app/usage sessions) — keeps the
    messaging/social/cloud/email bundle lists defined in exactly one place.

    Returns (category, subcategory, confidence).
    """
    bundle = bundle or ''
    if bundle in _MESSAGING_BUNDLES:
        return 'Messaging App', (display or bundle), 'high'
    if bundle in _SOCIAL_BUNDLES:
        return 'Social Media', (display or bundle), 'high'
    if bundle in _CLOUD_BUNDLES:
        return 'Cloud Storage', (display or bundle), 'high'
    if bundle in _EMAIL_BUNDLES:
        return 'Email Attachment', (display or bundle), 'high'
    if bundle in _APPLE_SYSTEM_BUNDLES:
        return 'Apple System App', (display or bundle), 'high'
    if bundle:
        return 'Third-Party App', (display or bundle), 'medium'
    return 'Unknown App', 'Unknown App', 'low'


def classify_app_session(bundle_id):
    """
    Classify a knowledgeC.db /app/usage session's bundle ID using the same
    category taxonomy as classify_asset_source(), so a "Messaging App" badge
    means the same thing whether it's attached to a photo or an app-usage
    session. Returns a dict matching classify_asset_source()'s shape minus
    the photo-specific fields (kind_subtype, is_mine, etc. don't apply here).
    """
    category, subcategory, confidence = categorize_bundle_id(bundle_id, None)
    return {
        'category':     category,
        'subcategory':  subcategory,
        'bundle_id':    bundle_id or None,
        'display_name': None,
        'confidence':   confidence,
    }


