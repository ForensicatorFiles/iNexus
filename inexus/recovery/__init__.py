"""
One module per forensic source, each attempting to recover deleted rows
from that source's freelist pages via sqlite_forensics/. Only invoked when
-recover-deleted is passed. Every recovered row carries recovered=True and
confidence="carved" and is kept visibly separate from confirmed live data
throughout this tool — never silently merged into the map, timeline,
places, or any other confirmed view.

    cache.py         recover_cache()          Cache.sqlite location history
    photos.py        recover_photos()         Photos.sqlite assets
    cloud_v2.py      recover_cloud_v2()       Cloud-V2.sqlite learned visits
    knowledgec.py    recover_knowledgec()     knowledgeC.db app usage
    sms.py           recover_sms()            sms.db messages
    calls.py         recover_calls()          CallHistory.storedata calls
    interactions.py  recover_interactions()   interactionC.db interactions
    addressbook.py   recover_addressbook()    AddressBook.sqlitedb contacts
"""
