class SMA2UploadInverterDataToPVOutputOrg(object):
    ## create an object suitable for uploading data to pboutput.org
    # @param db an SMADatabase object
    # @param pvoutput a pvoutput object
    # @param inv an SMAData2InverterConfigobject
    def __init__(self, db, inv, pvoutput):
        ## set to True to print way too much stuff to stdout
        self.print_verbose = True
        ## an SMADatabase object
        self.db = db
        ## a pvoutput object
        self.pvoutput = pvoutput
        ## an SMAData2InverterConfigobject
        self.inv = inv

    ## send a batch of datapoints to the server
    # @param batch a two-dimension array [[ timestamp,totalprod ], ...]
    def sendbatch(self, batch):
        self.pvoutput.addbatchstatus(inv.pvoutput_sid, batch)

    ## returns maximum datapoints the API will accept in a batch
    # @return an integer with the maximum batch length the API will accept
    def batch_length_max(self):
        return 30

    ## send entries to server
    # @param entries entries to send [[ timestamp,totalprod ], ...]
    # @todo sanity checking for too-old-dates should be made by callers
    # @todo move this batching into pvoutput
    def send_entries(self, entries):
        batch = []
        last_total_production = -1		# unlikely...

        too_old_in_days = self.pvoutput.days_ago_accepted_by_api()

        havesent = False
        timeout = 20
        for i in entries:
            timestamp = i[0]
            total_production = i[1]
            # print("t=" + str(timestamp) + " ("
            #       + time.strftime("%Y-%m-%d %H:%M",
            #                       time.localtime(timestamp)) + ")")
            # print("p=" + str(total_production))

            # 14 day limit on API - only upload the last 13 days of data:
            if (time.time() - timestamp) > (too_old_in_days*24*60*60 - 600):
                    print("Skipping too-old datapoint @" + str(timestamp))
                    continue

            batch.append([timestamp, total_production])

            last_total_production = total_production

            if len(batch) == self.batch_length_max():
                if havesent:
                    # if we do *not* wait, other requests can get served
                    # first.  The API wants stuff *in order*!  Sucks.
                    print("sleeping %d" % timeout)
                    time.sleep(timeout)
                else:
                    havesent = True
                self.sendbatch(batch)
                batch = []

        if batch:
                if havesent:
                    print("sleeping before sending final batch")
                    time.sleep(timeout)
                self.sendbatch(batch)

    ## filter out entries that we shouldn't upload to pvoutput.org
    # @param hwm the last datapoint [timestamp,generation] sent to server
    # @param statuses the list of statuses to trim
    # @return trimmed status list
    # @note each day needs a baseline-no-production-yet datapoint
    # @todo change this to screw with statuses in-place instead
    def trim_unwanted_unuploaded_statuses(self, hwm, statuses):
        skipping = False
        last = hwm
        ret = []
        while statuses:
            this = statuses.pop(0)
            if skipping:
                if statuses:
                    next = statuses[0]
                    if this[1] == next[1]:
                        pass		# keep skipping
                    else:
                        skipping = False
                        ret.append(this)
                else:
                    return ret
            else:			# not skipping
                if last[1] == this[1]:
                    skipping = True
                else:
                    ret.append(this)
            last = this
        return ret

    ## upload statuses that we do not believe are present on the server
    def upload_unuploaded_statuses_batch(self):
        hwm = db.pvoutput_get_hwm(inv.serial)
        if hwm is None:
            db.pvoutput_init_hwm(inv.serial, 0)
            hwm = db.pvoutput_get_hwm(inv.serial)

        print("hwm=%d" % hwm[0])
        entries = db.get_entries_younger_than(inv.serial, hwm)
        new_entries = self.trim_unwanted_unuploaded_statuses(hwm, entries)
        entries = new_entries
        if entries:
            self.send_entries(entries)
            new_hwm = entries[-1]
            new_hwm_timestamp = new_hwm[0]
            print("new hwm=" + str(new_hwm_timestamp))
            db.pvoutput_set_hwm(inv.serial, new_hwm_timestamp)
        else:
            print("No un-uploaded entries")

    ## trim entries off outputs for a single day that are pointless to upload
    # @param statuses to trim
    # @note statuses are trimmed in place
    # @note each day needs a baseline-no-production-yet datapoint
    def trim_unwanted_daily_statuses(self, statuses):
        while statuses:		# trim statuses off the front
            if len(statuses) > 1:
                if statuses[0][1] == statuses[1][1]:
                    # the next data point is the same as the first datapoint:
                    statuses.pop(0)
                else:
                    break
            else:
                break
        while statuses:		# trim statuses off the front
            if len(statuses) > 1:
                if statuses[-1][1] == statuses[-2][1]:
                    # last datapoint == second last datapoint
                    statuses.pop()
                else:
                    break
            else:
                break

    ## upload statuses for a specific day
    # @param day day to upload for
    def upload_statuses_for_day(self, day):
        entries = db.get_entries_for_day(inv.serial, day)
        # remove any entries which do not add information:
        self.trim_unwanted_daily_statuses(entries)
        self.send_entries(entries)

    ## print out a message only if we're verbose
    # @param message a message to print
    def verbose(self, message):
        if self.print_verbose:
            print(message)

    ## check that the db entries are accurately reflected on
    # pvoutput.org for date
    # @param date a datetime object - midnight, please
    # @todo take a... you know... date instead of a datetime?
    def reconcile_date(self, date):
        mydata = db.get_entries_for_day(inv.serial, date)

        # for prod in mydata:
        #     timestamp = prod[0]
        #     cumulative = prod[1]
        #     print("timestamp=%s cumulative=%s" % (timestamp, cumulative))

        theirdata = self.pvoutput.getstatus(inv.pvoutput_sid, date, None, None)
        # for output in theirdata:
        #     print("date=%s time=%s production=%s" \
        #            % (output[0], output[1], output[2]))

        my_last_delta = None

        first_production = None
        while 1:
            if not mydata:
                break
            if not theirdata:
                break
            mine = mydata[0]
            my_timestamp = mine[0]
            my_production = mine[1]

            if first_production is None:
                first_production = my_production

            # print("my_timestamp=%d my_production=%d" \
            #       % (my_timestamp, my_production))
            my_delta = mine[1] - first_production

            my_last_delta = my_delta

            theirs = theirdata[0]
            their_date = theirs[0]
            their_time = theirs[1]
            their_delta = theirs[2]
            their_datetime = self.pvoutput.parse_date_and_time(their_date,
                                                               their_time)
            their_timestamp = time.mktime(their_datetime.timetuple())
            # print("their_timestamp=%d their_delta=%d" \
            #       % (their_timestamp, their_delta))
            if their_timestamp > my_timestamp:
                mydata.pop(0)
                if (my_delta != 0):
                    # fred = datetime.datetime.utcfromtimestamp(my_timestamp)
                    x = time.strftime("%Y-%m-%d %H:%M",
                                      time.localtime(my_timestamp))
                    print("Extra datapoint from me: %s (%s) %s"
                          % (my_timestamp, x, my_delta))
            else:
                if their_timestamp < my_timestamp:
                    print("Extra datapoint from them: %s %s %s"
                          % (their_date, their_time, their_delta))
                    theirdata.pop(0)
                else:
                    if their_delta != my_delta:
                        print(("production mismatch (timestamp=%d)"
                               + " (them=%d us=%d)")
                              % (my_timestamp, their_delta, my_delta))
                    else:
                        self.verbose("ALL GOOD (them=%d us=%d) (them=%d us=%d)"
                                     % (their_timestamp, my_timestamp,
                                        their_delta, my_delta))
                    theirdata.pop(0)
                    mydata.pop(0)

        if theirdata:
            print("Thereq are %d on pvoutput.org which aren't in our data"
                  % len(theirdata))
            for output in theirdata:
                self.verbose("their extra: date=%s time=%s production=%s"
                             % (output[0], output[1], output[2]))

        printed_mydata_warning_once = False
        if mydata:
            for mine in mydata:
                my_delta = mine[1] - first_production
                if my_delta != my_last_delta:  # zeroes at end of day
                    if not printed_mydata_warning_once:
                        print(("There are %d extra readings in my database"
                               + "which are not on pvoutput.org")
                              % len(mydata))
                        printed_mydata_warning_once = True
                    self.verbose("my extra: timestamp=%s cumulative=%s"
                                 % (mine[0], my_delta))

    ## reconcile all data in my database against what is on pvoutput.org
    def reconcile(self):
        dates = db.midnights(inv.serial)
        now = datetime.datetime.now()
        for date in dates:
            if (date.date() == now.date()):
                # FIXME: API limit; can't get historical information for today
                continue
            limitdays = self.pvoutput.days_ago_accepted_by_api()
            if now - date < datetime.timedelta(days=limitdays):
                print("date: %s" % date)
                self.reconcile_date(date)

    ## simply print out data for inspection for a particular date/time
    # @param pvstyle_date e.g. "20141231"
    # @param pvstyle_time e.g. "12:30"
    def show_production_for_datapoint(self, pvstyle_date, pvstyle_time):
        datetime = self.pvoutput.parse_date_and_time(pvstyle_date,
                                                     pvstyle_time)
        timestamp = time.mktime(datetime.timetuple())
        datapoint = db.get_entry(inv.serial, timestamp)
        if datapoint is None:
            print("No such datapoint")
            return
        print("Production for (%s): %d" % (pvstyle_time, datapoint[1]))

    ## dodgy entry point to fix data already on server.
    # @param date date to work with in pvoutput format e.g. "20140731"
    # @param fix whether to attempt to fix the problem or not
    def do_date(self, date, fix):
        if fix:
            print(" delete data for a specific date (%s)" % date)
            day = self.pvoutput.parse_date_and_time(date, "00:00")
            self.pvoutput.deletestatus(inv.pvoutput_sid, day)

        if fix:
            print(" upload data for a specific date (%s)" % date)
            day = self.pvoutput.parse_date_and_time(date, "00:00")
            self.upload_statuses_for_day(day)
            sleep(20)  # so the reconcile works....

        if True:
            print("reconciling specific date (%s)" % date)
            somedate = self.pvoutput.parse_date_and_time(date, '00:00')
            self.reconcile_date(somedate)




SMA2UploadInverterDataToPVOutputOrg
